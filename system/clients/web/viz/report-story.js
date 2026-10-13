/* Detailed report: a request's resolution story as a looping three.js scene (GET /api/requests/{id}/story).

   A PS3-XMB-like wave and particle backdrop; the request flies in as a document, is stamped at triage, splits into its
   identification steps (the tool calls), the runs that worked it arrive with their tokens, then the changed folders fly
   out, open into their files, the files into their hunks (functions), everything breaks apart and recompiles into the
   merged result, which is stamped resolved. It loops. Drag to orbit, wheel to zoom, click a card to pause on it.

   Overlays: a ledger that scrolls in one entry per stage, each with slot-machine reels (token cost, tokens in, tokens
   out, time) that spin and land on the recorded value with a pop, and a totals row. Unrecorded values land on a dash.

   Costs are estimates unless the ledger says actual (the server labels them). Respects prefers-reduced-motion
   (a still composition; reels land at once). Cheap: one renderer at a time, built only when a disclosure opens,
   disposed on collapse, capped particles and cards, paused off-screen.

   Shared by the desktop app (../web/viz/report-story.js) and the web shell (/viz/report-story.js). The pure parts
   (formatting, reels, timeline, the disclosure controller with an injectable scene factory) run under node tests. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.GBoxReportStory = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const doc = env.document;
  const LIMITS = { steps: 10, runs: 4, folders: 8, filesPerFolder: 5, files: 24, hunks: 4, particles: 360, particlesReduced: 120 };
  const DASH = "\u2014";

  // ---------------------------------------------------------------- formatting (pure)
  const num = v => (typeof v === "number" && isFinite(v) ? v : null);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const escHtml = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  function fmtTokens(n) {
    n = num(n); if (n == null) return DASH;
    if (Math.abs(n) < 1000) return String(Math.round(n));
    if (Math.abs(n) < 1e6) return (n / 1e3).toFixed(n < 1e4 ? 2 : n < 1e5 ? 1 : 0) + "k";
    return (n / 1e6).toFixed(n < 1e7 ? 2 : 1) + "M";
  }
  // cost: {usd, kind: actual|estimate|unknown} -> "$0.0123" (actual) / "~$0.0123" (estimate) / dash
  function fmtCost(c) {
    const usd = num(c && typeof c === "object" ? c.usd : c);
    if (usd == null) return DASH;
    const s = usd === 0 ? "$0.00" : usd < 0.01 ? "$" + usd.toFixed(4) : usd < 1 ? "$" + usd.toFixed(3) : "$" + usd.toFixed(2);
    return (c && c.kind === "actual" ? "" : "~") + s;
  }
  function fmtTime(s) {
    s = num(s); if (s == null) return DASH;
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + String(s % 60).padStart(2, "0") + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + String(Math.floor(s % 3600 / 60)).padStart(2, "0") + "m";
    return Math.floor(s / 86400) + "d " + Math.floor(s % 86400 / 3600) + "h";
  }
  const REEL_KINDS = { cost: fmtCost, tokensIn: fmtTokens, tokensOut: fmtTokens, time: fmtTime };
  const reelText = (kind, value) => (REEL_KINDS[kind] || String)(value);

  // A reel's face `t` ms after it started spinning. Digits spin (seeded, so a frame is reproducible) and land left to
  // right from `land` ms, `stagger` ms apart; the reel pops for `pop` ms once the last digit lands. A dash (no value)
  // lands at once without spinning. Infinity = landed (reduced motion).
  function reelFace(target, t, { land = 900, stagger = 70, pop = 380, seed = 1 } = {}) {
    const text = String(target), missing = text === DASH, chars = [];
    let digits = 0;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (missing || !/[0-9]/.test(ch)) { chars.push({ ch, spinning: false }); continue; }
      const at = land + digits * stagger; digits++;
      if (t >= at) chars.push({ ch, spinning: false });
      else chars.push({ ch: String(Math.floor(rand(seed * 131 + i * 17 + Math.floor(t / 45)) * 10)), spinning: true });
    }
    const end = missing ? 0 : land + Math.max(0, digits - 1) * stagger;
    const landed = t >= end;
    return { text: chars.map(c => c.ch).join(""), chars, landed, popping: landed && !missing && t < end + pop, missing, end };
  }
  function rand(n) { const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); }

  // ---------------------------------------------------------------- story -> timeline (pure)
  const base = p => String(p || "").split("/").pop() || String(p || "");
  const tail = (p, n = 2) => { const parts = String(p || "").split("/").filter(Boolean); return parts.length ? parts.slice(-n).join("/") : "(repository root)"; };
  const metricsOf = st => ({ cost: st ? st.cost || null : null, tokensIn: st ? num(st.tokens_in) : null,
                             tokensOut: st ? num(st.tokens_out) : null, time: st ? num(st.duration_s) : null });
  // the changed files of every linked change, by folder, capped; folders with the most changed lines first
  function foldersOf(changes) {
    const files = new Map();
    for (const c of changes || []) for (const f of c.files || []) {
      const had = files.get(f.path);
      if (!had) { files.set(f.path, { path: f.path, folder: f.folder ?? f.path.split("/").slice(0, -1).join("/"), added: num(f.added), deleted: num(f.deleted), hunks: (f.hunks || []).slice(), hunksTotal: num(f.hunks_total) }); continue; }
      had.added = had.added != null && num(f.added) != null ? had.added + f.added : null;
      had.deleted = had.deleted != null && num(f.deleted) != null ? had.deleted + f.deleted : null;
      had.hunks.push(...(f.hunks || []));
    }
    const groups = new Map();
    for (const f of files.values()) { const g = groups.get(f.folder) || []; g.push(f); groups.set(f.folder, g); }
    const weight = f => (f.added ?? 0) + (f.deleted ?? 0);
    const sum = (list, k) => list.every(f => f[k] != null) ? list.reduce((a, f) => a + f[k], 0) : null;
    let all = [...groups.entries()].map(([path, list]) => ({ path, name: tail(path), files: list.sort((a, b) => weight(b) - weight(a)),
      added: sum(list, "added"), deleted: sum(list, "deleted") })).sort((a, b) => (b.files.reduce((s, f) => s + weight(f), 0) - a.files.reduce((s, f) => s + weight(f), 0)) || a.path.localeCompare(b.path));
    const shown = all.slice(0, LIMITS.folders);
    let budget = LIMITS.files;
    const folders = shown.map(g => {
      const take = Math.max(0, Math.min(LIMITS.filesPerFolder, budget)); budget -= take;
      const list = g.files.slice(0, take).map(f => ({ path: f.path, name: base(f.path), added: f.added, deleted: f.deleted,
        hunks: f.hunks.slice(0, LIMITS.hunks).map(h => ({ label: h.context || `@@ ${h.new ?? "?"}`, added: num(h.added), deleted: num(h.deleted), line: num(h.new) })),
        moreHunks: Math.max(0, (f.hunksTotal ?? f.hunks.length) - Math.min(LIMITS.hunks, f.hunks.length)) }));
      return { path: g.path, name: g.name, added: g.added, deleted: g.deleted, count: g.files.length, files: list, moreFiles: g.files.length - list.length };
    });
    return { folders, moreFolders: all.length - shown.length, fileCount: files.size };
  }
  const SUB = [["fly", 1.6, "Folders fly out"], ["files", 1.6, "Folders open into their files"], ["hunks", 1.4, "Files open into their changed functions"],
               ["break", 1.2, "The changes break apart"], ["recompile", 1.6, "and recompile into the merged result"]];
  // Phases of one loop (seconds), each tied to the story stage whose numbers its ledger entry shows.
  function timeline(story) {
    const s = story || {}, stages = Array.isArray(s.stages) ? s.stages : [], req = s.request || {};
    const of = key => stages.filter(x => x && x.key === key);
    const phases = [], entries = [];
    let t = 0;
    const add = (key, label, sub, dur, extra = {}) => { const p = { key, label, sub: sub || "", t0: t, t1: t + dur, ...extra }; phases.push(p); t += dur; return p; };
    const entry = (p, st, label, extra = {}) => entries.push({ key: p.key, label, at: +(p.t0 + 0.15).toFixed(3), metrics: metricsOf(st), stage: st || null, ...extra });
    const intake = of("intake")[0], triage = of("triage")[0], identify = of("identify")[0];
    entry(add("intake", "Request filed", `#${req.number ?? "?"} ${req.title || ""}`.trim(), 2.2), intake, "Filed \u2192 claimed");
    entry(add("triage", "Triage", triage ? triage.detail : "not claimed yet", 1.6), triage, "Triage");
    const steps = (s.identification || []).slice(0, LIMITS.steps).map(x => ({ label: x.action || "step", status: x.status || "", source: x.source || "",
      input: x.input || "", result: x.result || "", ts: num(x.ts), duration: num(x.duration_s) }));
    const nSteps = num(s.identification_total) ?? steps.length;
    entry(add("identify", "Identification", nSteps ? `${nSteps} tool call${nSteps === 1 ? "" : "s"} and steps` : "no tool calls recorded",
              clamp(1.2 + 0.35 * steps.length, 1.6, 5)), identify, "Identification");
    const works = of("work").slice(0, LIMITS.runs);
    if (works.length) {
      const each = Math.max(1.1, Math.min(1.8, 5.4 / works.length));
      works.forEach((w, i) => entry(add("work", w.label || "Run", w.detail, each, { run: i }), w, w.label || "Run"));
    } else entry(add("work", "Work", "no agent run recorded", 1.1, { run: -1 }), null, "Work");
    const tree = foldersOf(s.changes);
    const ch = of("changes"), merged = (s.changes || []).find(c => c.state === "merged") || (s.changes || [])[0] || null;
    const chStage = ch.length ? { ...ch[0], duration_s: ch.length === 1 ? ch[0].duration_s : null } : null;
    const chLabel = merged ? (merged.number ? `PR #${merged.number} \u00b7 ${merged.state}` : `Code changes \u00b7 ${merged.state}`) : "Code changes";
    const lines = s.totals ? [num(s.totals.added), num(s.totals.deleted)] : [null, null];
    const chDetail = tree.fileCount ? `${tree.fileCount} file${tree.fileCount === 1 ? "" : "s"} in ${tree.folders.length + tree.moreFolders} folder${tree.folders.length + tree.moreFolders === 1 ? "" : "s"}`
      + (lines[0] != null ? ` \u00b7 +${lines[0]} \u2212${lines[1]}` : " \u00b7 line counts unavailable") : (merged ? "files unavailable" : "no linked code change");
    if (tree.fileCount) {
      SUB.forEach(([sub, dur, words], i) => { const p = add("changes", chLabel, i ? words : chDetail, dur, { part: sub }); if (!i) entry(p, chStage, chLabel, { detail: chDetail }); });
    } else entry(add("changes", chLabel, chDetail, 1.3, { part: "none" }), chStage, chLabel, { detail: chDetail });
    const res = of("resolution")[0];
    const done = req.status === "done";
    const resolve = add("resolve", done ? "Resolved" : `Status: ${String(req.status || "unknown").replace("_", " ")}`, res ? res.detail : "", 2.2);
    entry(resolve, res, done ? "Resolved (filed \u2192 done)" : "Open so far");
    add("hold", "", "", 1.6, { hold: true });
    const tot = s.totals || {};
    const totals = { cost: tot.cost || null, tokensIn: num(tot.tokens_in), tokensOut: num(tot.tokens_out), time: num(tot.duration_s), elapsed: !!tot.elapsed,
                     at: +(resolve.t0 + 0.7).toFixed(3) };
    return { phases, entries, totals, length: +t.toFixed(3), steps, moreSteps: Math.max(0, nSteps - steps.length),
             runs: works.map(w => ({ label: w.label, detail: w.detail, tokensIn: num(w.tokens_in), tokensOut: num(w.tokens_out), cost: w.cost || null, time: num(w.duration_s) })),
             ...tree, merged: merged ? { label: chLabel, sha: merged.merged_sha || null, url: merged.url || null, state: merged.state } : null,
             doc: { number: req.number, title: req.title || "Request", status: req.status || "" }, done, missing: s.missing || [] };
  }
  // the phase at loop time t (seconds): {phase, index, p (0..1 through it)}
  function phaseAt(tl, t) {
    const L = tl.length || 1, x = ((t % L) + L) % L;
    let i = tl.phases.findIndex(ph => x >= ph.t0 && x < ph.t1);
    if (i < 0) i = tl.phases.length - 1;
    const ph = tl.phases[i];
    return { phase: ph, index: i, p: clamp((x - ph.t0) / Math.max(1e-6, ph.t1 - ph.t0), 0, 1), t: x };
  }
  // when (loop seconds) a key/part starts and ends
  function span(tl, key, part) {
    const list = tl.phases.filter(p => p.key === key && (part == null || p.part === part));
    return list.length ? [list[0].t0, list[list.length - 1].t1] : [null, null];
  }

  // a textual summary (no WebGL, and the card for the whole story)
  function summaryHtml(story, esc = escHtml) {
    const tl = timeline(story), row = (k, v) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
    const out = [`<table class="rs-sum">`];
    for (const e of tl.entries) out.push(row(e.label, [fmtCost(e.metrics.cost), `${fmtTokens(e.metrics.tokensIn)} in`, `${fmtTokens(e.metrics.tokensOut)} out`, fmtTime(e.metrics.time)].join(" \u00b7 ")));
    out.push(row("Total", [fmtCost(tl.totals.cost), `${fmtTokens(tl.totals.tokensIn)} in`, `${fmtTokens(tl.totals.tokensOut)} out`, fmtTime(tl.totals.time) + (tl.totals.elapsed ? " so far" : "")].join(" \u00b7 ")));
    out.push("</table>");
    if (tl.missing.length) out.push(`<p class="rs-missing">Not recorded: ${esc(tl.missing.join(" "))}</p>`);
    return out.join("");
  }

  // ---------------------------------------------------------------- styles and DOM
  const CSS = `
.rs-disclosure { margin:6px 0 0; } .rs-disclosure > summary { cursor:pointer; color:var(--mut,#9aa3b5); font-size:12px; user-select:none; }
.rs-disclosure > summary:hover { color:var(--fg,#e8ebf2); }
.rs-panel { position:relative; height:440px; margin-top:6px; border-radius:10px; overflow:hidden; border:1px solid var(--line,#2a2f3a);
  background:radial-gradient(ellipse at 50% 125%, #2a86c4 0%, #0f3e74 38%, #071a36 70%, #030814 100%); color:#eef4ff; font-size:12px; }
.rs-panel.rs-full { height:100%; margin:0; border:0; border-radius:0; }
.rs-panel .rs-loading, .rs-panel .rs-error { position:absolute; inset:0; display:grid; place-items:center; color:#cfe2ff; padding:20px; text-align:center; }
.rs-canvas { position:absolute; inset:0; width:100%; height:100%; display:block; cursor:grab; }
.rs-canvas:active { cursor:grabbing; }
.rs-banner { position:absolute; left:12px; top:10px; right:40%; pointer-events:none; text-shadow:0 1px 6px #000c; }
.rs-banner .rs-n { font:600 10px/1 ui-monospace,Consolas,monospace; letter-spacing:.12em; color:#9fd0ff; text-transform:uppercase; }
.rs-banner b { display:block; font-size:17px; font-weight:600; margin-top:3px; letter-spacing:.01em; }
.rs-banner span.rs-sub { display:block; color:#cfe2ffcc; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rs-ledger { position:absolute; left:10px; bottom:10px; width:min(360px, 46%); display:flex; flex-direction:column; gap:4px; pointer-events:none; }
.rs-list { display:flex; flex-direction:column; gap:4px; max-height:190px; overflow:hidden; justify-content:flex-end; }
.rs-panel.rs-full .rs-list { max-height:46vh; }
.rs-entry, .rs-total { background:#05112acc; border:1px solid #7fb8ff33; border-radius:8px; padding:5px 8px; backdrop-filter:blur(3px);
  animation:rs-in .45s cubic-bezier(.2,.9,.25,1) both; }
.rs-total { border-color:#ffd76a66; background:#140f02d0; }
.rs-entry .rs-l, .rs-total .rs-l { display:block; font-size:11px; color:#cfe2ff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rs-total .rs-l { color:#ffe7a3; font-weight:600; }
.rs-reels { display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; margin-top:3px; }
.rs-reel { display:flex; flex-direction:column; min-width:0; }
.rs-reel small { font-size:9px; letter-spacing:.08em; text-transform:uppercase; color:#8fb3e0; }
.rs-reel output { font:600 13px/1.25 ui-monospace,Consolas,monospace; color:#fff; white-space:nowrap; overflow:hidden; display:inline-block; transform-origin:left center; }
.rs-reel output.rs-spin { color:#9fd0ff; filter:blur(.4px); }
.rs-reel output.rs-pop { animation:rs-pop .38s ease-out; color:#fff6c2; text-shadow:0 0 10px #ffe680; }
.rs-reel output.rs-none { color:#8fa2bd; }
.rs-card { position:absolute; right:10px; top:10px; width:min(330px, 44%); max-height:calc(100% - 64px); overflow:auto; background:#06122bee; border:1px solid #7fb8ff55;
  border-radius:10px; padding:9px 11px; box-shadow:0 10px 30px #000a; }
.rs-card[hidden] { display:none; }
.rs-card h4 { margin:0 0 4px; font-size:13px; overflow-wrap:anywhere; } .rs-card .rs-kind { display:block; font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:#9fd0ff; }
.rs-card table, .rs-sum { border-collapse:collapse; width:100%; } .rs-card th, .rs-sum th { text-align:left; color:#8fb3e0; font-weight:500; padding:2px 8px 2px 0; vertical-align:top; white-space:nowrap; }
.rs-card td, .rs-sum td { padding:2px 0; overflow-wrap:anywhere; }
.rs-card pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:140px; overflow:auto; background:#020814; border-radius:6px; padding:5px 7px; font:11px/1.4 ui-monospace,Consolas,monospace; margin:4px 0; }
.rs-controls { position:absolute; right:10px; bottom:10px; display:flex; gap:6px; }
.rs-controls button { background:#0b2350cc; color:#eef4ff; border:1px solid #7fb8ff55; border-radius:6px; padding:3px 9px; font-size:11px; cursor:pointer; }
.rs-controls button:hover { background:#173a78; }
.rs-hint { position:absolute; left:50%; transform:translateX(-50%); bottom:12px; font-size:10px; color:#cfe2ff88; pointer-events:none; white-space:nowrap; }
.rs-missing { color:#ffcf8a; font-size:11px; margin:6px 0 0; }
@keyframes rs-in { from { transform:translateY(14px); opacity:0; } to { transform:none; opacity:1; } }
@keyframes rs-pop { 0% { transform:scale(1); } 35% { transform:scale(1.32); } 100% { transform:scale(1); } }
#reportstory { display:none; position:fixed; inset:80px 0 28px 0; z-index:1150; background:#030814; color:#eef4ff; flex-direction:column; }
#reportstory.on { display:flex; }
#reportstory .rs-head { display:flex; align-items:center; gap:10px; padding:8px 14px; border-bottom:1px solid #1d2b45; background:#06101f; }
#reportstory .rs-head b { flex:1; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#reportstory .rs-body { position:relative; flex:1; min-height:0; }
@media (prefers-reduced-motion: reduce) { .rs-entry, .rs-total, .rs-reel output.rs-pop { animation:none; } }
`;
  function ensureStyle() {
    if (!doc || doc.getElementById("rs-style")) return;
    const st = doc.createElement("style"); st.id = "rs-style"; st.textContent = CSS; (doc.head || doc.body).append(st);
  }
  const reducedMotion = () => { try { return !!env.matchMedia && env.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };
  const REELS = [["cost", "Token cost"], ["tokensIn", "Tokens in"], ["tokensOut", "Tokens out"], ["time", "Time"]];
  function reelsHtml() { return `<div class="rs-reels">${REELS.map(([k, l]) => `<span class="rs-reel"><small>${l}</small><output data-reel="${k}">${DASH}</output></span>`).join("")}</div>`; }

  // ---------------------------------------------------------------- the scene (three.js r128)
  function createScene(container, story, opts = {}) {
    story = story || {};
    const THREE = env.THREE, esc = opts.esc || escHtml, tl = timeline(story), still = opts.reducedMotion ?? reducedMotion();
    ensureStyle();
    container.innerHTML = `<canvas class="rs-canvas" aria-label="Animated story of how this request was resolved"></canvas>
      <div class="rs-banner" aria-live="polite"><span class="rs-n"></span><b></b><span class="rs-sub"></span></div>
      <div class="rs-ledger"><div class="rs-list"></div></div>
      <div class="rs-card" hidden></div>
      <div class="rs-controls"><button type="button" data-rs="play">${still ? "Play" : "Pause"}</button><button type="button" data-rs="restart">Restart</button><button type="button" data-rs="summary">Numbers</button></div>
      <div class="rs-hint">drag to orbit \u00b7 wheel to zoom \u00b7 click a card to pause on it</div>`;
    const $ = sel => container.querySelector(sel), canvas = $(".rs-canvas");
    const S = { playing: !still, clock: still ? stillTime(tl) : 0, visible: true, raf: 0, last: 0, disposed: false, focus: null, shown: new Set(), reels: [], totalsShown: false,
                lastPhase: -1, detachedSince: 0, dirty: true };
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(env.devicePixelRatio || 1, opts.full ? 2 : 1.5));
    renderer.setClearColor(0x000000, 0);
    const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(50, 2, 0.1, 400);
    const orbit = { yaw: 0, pitch: 0.1, dist: 17, target: new THREE.Vector3(0, 0.3, 0), goal: new THREE.Vector3(0, 0.3, 0), goalDist: 17, drag: null, touched: -1e9 };
    const disposables = [];
    const keep = o => { disposables.push(o); return o; };

    // --- backdrop: XMB waves and drifting particles
    const waveV = `uniform float uTime; uniform float uPhase; varying vec2 vUv;
      void main(){ vUv = uv; vec3 p = position;
        p.y += sin(p.x*0.12 + uTime*0.35 + uPhase)*1.7 + sin(p.x*0.27 - uTime*0.22 + uPhase*2.0)*0.7;
        p.z += sin(p.x*0.18 + uTime*0.27 + uPhase)*1.2;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0); }`;
    const waveF = `uniform vec3 uColor; uniform float uAlpha; varying vec2 vUv;
      void main(){ float d = abs(vUv.y - 0.5) * 2.0; float glow = pow(1.0 - d, 2.5); float rim = smoothstep(0.86, 0.98, d) * (1.0 - smoothstep(0.98, 1.0, d));
        gl_FragColor = vec4(uColor, (0.05 + glow * 0.22 + rim * 0.35) * uAlpha); }`;
    const waves = [[0x9fd8ff, 0, 4.2, -14, 0.95], [0xc8e6ff, 2.1, 2.6, -11, 0.7], [0x6fb0ff, 4.0, 5.5, -18, 0.55]].map(([color, phase, h, z, a]) => {
      const m = keep(new THREE.ShaderMaterial({ vertexShader: waveV, fragmentShader: waveF, transparent: true, depthWrite: false, side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending, uniforms: { uTime: { value: 0 }, uPhase: { value: phase }, uColor: { value: new THREE.Color(color) }, uAlpha: { value: a } } }));
      const g = keep(new THREE.PlaneGeometry(90, h, 120, 6)), mesh = new THREE.Mesh(g, m);
      mesh.position.set(0, -3.2, z); mesh.rotation.x = -0.35; scene.add(mesh); return m;
    });
    const nP = Math.min(opts.particles || LIMITS.particles, still ? LIMITS.particlesReduced : LIMITS.particles);
    const pPos = new Float32Array(nP * 3), pSeed = new Float32Array(nP);
    for (let i = 0; i < nP; i++) { pPos[i * 3] = rand(i + 1) * 80 - 40; pPos[i * 3 + 1] = -3.2 + (rand(i + 7) - 0.5) * 7; pPos[i * 3 + 2] = -16 + rand(i + 13) * 12; pSeed[i] = rand(i + 29); }
    const pGeo = keep(new THREE.BufferGeometry());
    pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3)); pGeo.setAttribute("aSeed", new THREE.BufferAttribute(pSeed, 1));
    const pMat = keep(new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uTime: { value: 0 }, uScale: { value: renderer.getPixelRatio() } },
      vertexShader: `attribute float aSeed; uniform float uTime; uniform float uScale; varying float vA;
        void main(){ vec3 p = position; p.x = mod(p.x + uTime * (0.4 + aSeed * 0.9) + 40.0, 80.0) - 40.0;
          p.y += sin(p.x * 0.12 + uTime * 0.35) * 1.7 + sin(uTime * 0.7 + aSeed * 6.28) * 0.3;
          vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_PointSize = uScale * (1.5 + aSeed * 3.5) * (22.0 / -mv.z);
          gl_Position = projectionMatrix * mv; vA = 0.25 + 0.75 * fract(aSeed * 7.0); }`,
      fragmentShader: `varying float vA; void main(){ float r = length(gl_PointCoord - 0.5); if (r > 0.5) discard; gl_FragColor = vec4(0.86, 0.94, 1.0, (1.0 - r * 2.0) * vA * 0.75); }` }));
    scene.add(new THREE.Points(pGeo, pMat));

    // --- cards: a canvas texture on a plane
    const content = new THREE.Group(); scene.add(content);
    const nodes = [];
    function texture(w, h, draw) {
      const c = doc.createElement("canvas"), pw = Math.min(512, Math.round(w * 150)); c.width = pw; c.height = Math.max(16, Math.round(pw * h / w));
      const g = c.getContext("2d"); draw(g, c.width, c.height);
      const t = keep(new THREE.CanvasTexture(c)); t.minFilter = THREE.LinearFilter; return t;
    }
    function rounded(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
    function fit(g, text, max) { text = String(text ?? ""); if (g.measureText(text).width <= max) return text; while (text.length > 1 && g.measureText(text + "\u2026").width > max) text = text.slice(0, -1); return text + "\u2026"; }
    function cardTex(w, h, { bg = "#0d2a55", edge = "#9fd0ff", title = "", sub = "", sub2 = "", icon = "", ink = "#ffffff", tab = false }) {
      return texture(w, h, (g, W, H) => {
        const r = H * 0.14, top = tab ? H * 0.16 : 0;
        if (tab) { g.fillStyle = edge; rounded(g, W * 0.04, 0, W * 0.38, H * 0.3, r * 0.6); g.fill(); }
        g.fillStyle = bg; rounded(g, 2, top + 2, W - 4, H - top - 4, r); g.fill();
        g.lineWidth = Math.max(2, H * 0.03); g.strokeStyle = edge; g.stroke();
        const pad = W * 0.06; let x = pad;
        if (icon) { g.font = `${Math.round(H * 0.34)}px Segoe UI Emoji, Segoe UI, sans-serif`; g.textBaseline = "middle"; g.fillStyle = ink; g.fillText(icon, x, top + (H - top) * 0.45); x += H * 0.44; }
        g.textBaseline = "alphabetic"; g.fillStyle = ink; g.font = `600 ${Math.round((H - top) * (sub ? 0.24 : 0.3))}px Segoe UI, sans-serif`;
        g.fillText(fit(g, title, W - x - pad), x, top + (H - top) * (sub ? (sub2 ? 0.34 : 0.42) : 0.6));
        if (sub) { g.font = `${Math.round((H - top) * 0.17)}px Segoe UI, sans-serif`; g.fillStyle = "#cfe2ff"; g.fillText(fit(g, sub, W - x - pad), x, top + (H - top) * (sub2 ? 0.6 : 0.74)); }
        if (sub2) { g.font = `${Math.round((H - top) * 0.17)}px ui-monospace, Consolas, monospace`; g.fillStyle = "#9ff0b8"; g.fillText(fit(g, sub2, W - x - pad), x, top + (H - top) * 0.84); }
      });
    }
    const geoCache = new Map();
    const plane = (w, h) => { const k = w + "x" + h; if (!geoCache.has(k)) geoCache.set(k, keep(new THREE.PlaneGeometry(w, h))); return geoCache.get(k); };
    function node(w, h, tex, info, pose, color) {
      const mat = keep(new THREE.MeshBasicMaterial(tex ? { map: tex, transparent: true, depthWrite: false, side: THREE.DoubleSide } : { color, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      const mesh = new THREE.Mesh(plane(w, h), mat); mesh.visible = false; content.add(mesh);
      const n = { mesh, mat, info, pose }; mesh.userData.node = n; nodes.push(n); return n;
    }
    const statusColor = st => /fail|error|reject|block/i.test(st) ? ["#3a0d14", "#ff6b7a"] : /run|progress|queued|await/i.test(st) ? ["#3a2a06", "#ffc04d"] : /finish|done|succe|ok|complete|merged/i.test(st) ? ["#0b3320", "#5ee89a"] : ["#13244a", "#9fb8ff"];
    const pm = (a, d) => (a == null ? "" : `+${a} \u2212${d ?? "?"}`);
    const E = { out: t => 1 - Math.pow(1 - clamp(t, 0, 1), 3), inout: t => (t = clamp(t, 0, 1), t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
                back: t => { t = clamp(t, 0, 1); const c = 1.9; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); } };
    const lerp = (a, b, k) => a + (b - a) * k;
    const P = (x, y, z, s = 1, o = 1, ry = 0, rz = 0) => ({ x, y, z, s, o, ry, rz });
    const [iA, iB] = span(tl, "identify"), [wA] = span(tl, "work"), [cA] = span(tl, "changes"), [rA, rB] = span(tl, "resolve");
    const sub = k => span(tl, "changes", k);
    const [fly0, fly1] = sub("fly"), [fil0, fil1] = sub("files"), [hun0, hun1] = sub("hunks"), [brk0, brk1] = sub("break"), [rec0, rec1] = sub("recompile");
    const hasTree = tl.folders.length > 0, end = tl.length - 0.5;
    const fade = t => (t > end ? clamp(1 - (t - end) / 0.5, 0, 1) : 1);

    // the request: flies in, stamped at triage, then steps back to the corner
    const docPose = t => {
      if (t < 0) return null;
      const k = E.out(t / 1.6), corner = E.inout((t - wA) / 0.9);
      let p = P(lerp(0, 0, k), lerp(0.4, 0.6, k), lerp(-70, 0, k), 1, k, (1 - k) * Math.PI * 3);
      if (t >= wA) p = P(lerp(0, -8.6, corner), lerp(0.6, 3.6, corner), lerp(0, -2.5, corner), lerp(1, 0.55, corner), 1);
      if (!tl.merged && t >= rA) { const back = E.inout((t - rA) / 0.8); p = P(lerp(-8.6, 0, back), lerp(3.6, 0.6, back), lerp(-2.5, 1, back), lerp(0.55, 1, back), 1); }
      p.o *= fade(t); return p;
    };
    const docN = node(3, 3.9, texture(3, 3.9, (g, W, H) => {
      g.fillStyle = "#f4f7ff"; rounded(g, 2, 2, W - 4, H - 4, W * 0.05); g.fill();
      g.fillStyle = "#d8e2f5"; g.beginPath(); g.moveTo(W * 0.78, 2); g.lineTo(W - 2, H * 0.17); g.lineTo(W * 0.78, H * 0.17); g.closePath(); g.fill();
      g.fillStyle = "#1a2c52"; g.font = `700 ${Math.round(H * 0.075)}px Segoe UI, sans-serif`; g.fillText(`#${tl.doc.number ?? "?"}`, W * 0.08, H * 0.12);
      g.font = `600 ${Math.round(H * 0.052)}px Segoe UI, sans-serif`;
      const words = String(tl.doc.title).split(/\s+/); let line = "", y = H * 0.22;
      for (const w of words) { const next = line ? line + " " + w : w; if (g.measureText(next).width > W * 0.84 && line) { g.fillText(line, W * 0.08, y); y += H * 0.065; line = w; if (y > H * 0.5) break; } else line = next; }
      if (line && y <= H * 0.5) g.fillText(line, W * 0.08, y);
      g.fillStyle = "#c3cfe6"; for (let i = 0; i < 7; i++) g.fillRect(W * 0.08, H * (0.58 + i * 0.055), W * (0.84 - (i % 3) * 0.17), H * 0.018);
    }), { kind: "Request", title: `#${tl.doc.number ?? "?"} ${tl.doc.title}`, rows: [["Status", tl.doc.status], ...tl.entries.slice(0, 2).map(e => [e.label, e.stage?.detail || ""])] }, docPose);
    // the triage stamp rides on the document
    const tri = (story.triage || {});
    const stampN = node(2.3, 1.0, texture(2.3, 1.0, (g, W, H) => {
      g.strokeStyle = tri.by ? "#ff4d5e" : "#9aa3b5"; g.lineWidth = H * 0.08; rounded(g, H * 0.08, H * 0.08, W - H * 0.16, H - H * 0.16, H * 0.16); g.stroke();
      g.fillStyle = g.strokeStyle; g.font = `800 ${Math.round(H * 0.36)}px Segoe UI, sans-serif`; g.textAlign = "center"; g.fillText(tri.by ? "TRIAGED" : "UNCLAIMED", W / 2, H * 0.5);
      g.font = `600 ${Math.round(H * 0.17)}px Segoe UI, sans-serif`; g.fillText(fit(g, [tri.by, tri.agent].filter(Boolean).join(" \u00b7 ") || "nobody yet", W * 0.86), W / 2, H * 0.78);
    }), { kind: "Triage", title: tri.by ? `Claimed by ${tri.by}` : "Not claimed yet", rows: [["Agent / model", tri.agent || DASH], ["Via", tri.tool || DASH], ["Evidence", tri.evidence || DASH],
          ["Waited", fmtTime(tri.wait_s)], ["At", tri.at ? new Date(tri.at * 1000).toLocaleString() : DASH]] }, t => {
      const [a] = span(tl, "triage"), d = docPose(t); if (!d || t < a) return null;
      const k = clamp((t - a) / 0.35, 0, 1);
      return P(d.x + 0.35 * d.s, d.y - 0.9 * d.s, d.z + 0.05, d.s * lerp(3.2, 1, E.out(k)), d.o * k, 0, -0.18);
    });
    stampN.mesh.renderOrder = 2;
    // identification: the document splits into its steps (an arc above), which retire to a column on the left
    const nS = tl.steps.length;
    tl.steps.forEach((st, i) => {
      const [bg, edge] = statusColor(st.status), a = nS > 1 ? lerp(-1.05, 1.05, i / (nS - 1)) : 0;
      const at = iA + (iB - iA) * 0.75 * (nS > 1 ? i / (nS - 1) : 0);
      node(2.3, 0.86, cardTex(2.3, 0.86, { bg, edge, title: st.label, sub: st.input || st.result || st.source, sub2: st.status }),
        { kind: "Identification step", title: st.label, rows: [["Status", st.status || DASH], ["By", st.source || DASH], ["Input", st.input || DASH], ["Result", st.result || DASH],
          ["Took", fmtTime(st.duration)]] },
        t => {
          if (t < at) return null;
          const k = E.back((t - at) / 0.7), d = docPose(Math.min(t, at)) || P(0, 0.6, 0);
          let p = P(lerp(d.x, Math.sin(a) * 6.4, k), lerp(d.y, 3.0 + Math.cos(a) * 1.1 - 0.4, k), lerp(d.z, -0.8 - Math.abs(a) * 1.2, k), lerp(0.2, 1, clamp(k, 0, 1.2)), clamp(k * 1.5, 0, 1));
          const retire = cA != null ? E.inout((t - cA) / 1.0) : 0;
          if (retire > 0) p = P(lerp(p.x, -12.6, retire), lerp(p.y, 2.6 - i * 0.62, retire), lerp(p.z, -5, retire), lerp(1, 0.62, retire), lerp(1, 0.55, retire));
          p.o *= fade(t); return p;
        });
    });
    if (tl.moreSteps) node(1.6, 0.5, cardTex(1.6, 0.5, { title: `+${tl.moreSteps} more`, bg: "#0b1a33", edge: "#5d7bb0" }), { kind: "Identification", title: `${tl.moreSteps} more steps`, rows: [] },
      t => (t < iB ? null : P(-12.6, 2.6 - nS * 0.62, -5, 0.62, (cA != null && t > cA ? 0.55 : clamp((t - iB) / 0.4, 0, 1)) * fade(t))));
    // the runs that worked it, with their tokens, on the right
    const works = tl.phases.filter(p => p.key === "work" && p.run >= 0);
    tl.runs.forEach((r, k) => {
      const ph = works[k]; if (!ph) return;
      node(2.9, 1.15, cardTex(2.9, 1.15, { bg: "#0f2b1f", edge: "#5ee8b0", icon: "\u2699", title: r.label, sub: `${fmtTokens(r.tokensIn)} in \u00b7 ${fmtTokens(r.tokensOut)} out \u00b7 ${fmtCost(r.cost)}`, sub2: fmtTime(r.time) }),
        { kind: "Run", title: r.label, rows: [["Tokens in", fmtTokens(r.tokensIn)], ["Tokens out", fmtTokens(r.tokensOut)], ["Cost", fmtCost(r.cost) + (r.cost?.basis ? ` (${r.cost.basis})` : "")],
          ["Time", fmtTime(r.time)], ["Usage from", r.detail || DASH]] },
        t => {
          if (t < ph.t0) return null;
          const k2 = E.out((t - ph.t0) / 0.8), live = t < ph.t1 ? 1 + 0.05 * Math.sin(t * 9) : 1;
          return P(lerp(15, 9.2, k2), lerp(1.5, 3.4 - k * 1.45, k2), lerp(-8, -1.6, k2), live * (cA != null && t > cA ? 0.8 : 1), k2 * fade(t), (1 - k2) * -1.2);
        });
    });
    // the code: folders fly out, open into files, files into hunks; everything breaks apart and recompiles
    const F = tl.folders.length, seeds = [];
    const scatter = (id, p, t) => {
      if (t < brk0) return p;
      const s = seeds[id] || (seeds[id] = [rand(id * 3 + 1) * 2 - 1, rand(id * 3 + 2) * 2 - 1, rand(id * 3 + 3) * 2 - 1]);
      const b = E.out((t - brk0) / (brk1 - brk0)), mag = 3.2 + 2.4 * rand(id + 91);
      let q = P(p.x + s[0] * mag * b, p.y + s[1] * mag * b, p.z + s[2] * mag * b + 1.2 * b, p.s, p.o, s[1] * 2.4 * b, s[0] * 2.4 * b);
      if (t >= rec0) {
        const r = E.inout((t - rec0) / (rec1 - rec0));
        q = P(lerp(q.x, 0, r), lerp(q.y, 0.3, r), lerp(q.z, 2.2, r), q.s * (1 - r * 0.95), q.o * (1 - r * 0.7), q.ry * (1 - r), q.rz * (1 - r) + r * 6);
        if (r >= 1) return null;
      }
      return q;
    };
    let ids = 0;
    tl.folders.forEach((f, i) => {
      const fx = (i - (F - 1) / 2) * 3.15, fy = 1.7, fz = 0.6 - Math.abs(fx) * 0.05, at = fly0 + i * Math.min(0.12, 1.0 / Math.max(1, F)), id = ids++;
      const folderPose = t => {
        if (t < at || t >= rec1) return null;
        const k = E.back((t - at) / 0.9), d = docPose(at) || P(-8.6, 3.6, -2.5);
        return scatter(id, P(lerp(d.x, fx, k), lerp(d.y, fy, k), lerp(d.z, fz, k), lerp(0.25, 1, clamp(k, 0, 1.2)), clamp(k * 2, 0, 1), (1 - clamp(k, 0, 1)) * 2), t);
      };
      node(2.5, 1.55, cardTex(2.5, 1.55, { bg: "#3b2a07", edge: "#ffc94d", tab: true, icon: "\uD83D\uDCC1", title: f.name, sub: `${f.count} file${f.count === 1 ? "" : "s"}`, sub2: pm(f.added, f.deleted) }),
        { kind: "Folder", title: f.path || "(repository root)", rows: [["Files changed", String(f.count)], ["Lines", f.added == null ? "line counts unavailable" : pm(f.added, f.deleted)]] }, folderPose);
      f.files.forEach((file, j) => {
        const fid = ids++, ax = fx, ay = fy - 1.35 - j * 0.98, at2 = fil0 + j * 0.16 + i * 0.04;
        const filePose = t => {
          if (t < at2 || t >= rec1) return null;
          const k = E.back((t - at2) / 0.7);
          return scatter(fid, P(fx, lerp(fy, ay, k), lerp(fz, fz + 0.15, k), lerp(0.2, 1, clamp(k, 0, 1.2)), clamp(k * 2, 0, 1)), t);
        };
        const [bg, edge] = file.added == null ? ["#16264a", "#9fb8ff"] : file.deleted > file.added ? ["#3a0d18", "#ff8a9a"] : ["#0d3322", "#7cf0b0"];
        node(1.7, 0.78, cardTex(1.7, 0.78, { bg, edge, icon: "\uD83D\uDCC4", title: file.name, sub2: pm(file.added, file.deleted) || "lines n/a" }),
          { kind: "File", title: file.path, rows: [["Lines", file.added == null ? "line counts unavailable" : pm(file.added, file.deleted)],
            ["Changed functions", file.hunks.map(h => h.label).join(", ") || DASH], ...(file.moreHunks ? [["More hunks", String(file.moreHunks)]] : [])] }, filePose);
        file.hunks.forEach((h, q) => {
          const hid = ids++, hx = ax + 1.08 + (q % 2) * 0.4, hy = ay + 0.17 - Math.floor(q / 2) * 0.34, at3 = hun0 + q * 0.12 + j * 0.05;
          const color = h.added == null ? 0x7f9fd6 : (h.deleted || 0) > (h.added || 0) ? 0xff6b7a : (h.deleted || 0) > 0 ? 0xffc04d : 0x5ee89a;
          node(0.34, 0.26, null, { kind: "Changed function / hunk", title: h.label, rows: [["In", file.path], ["Lines", pm(h.added, h.deleted) || DASH], ["Starts at line", h.line ?? DASH]] },
            t => {
              if (t < at3 || t >= rec1) return null;
              const k = E.back((t - at3) / 0.5);
              return scatter(hid, P(lerp(ax, hx, k), lerp(ay, hy, k), fz + 0.3, clamp(k, 0, 1.2), clamp(k * 2, 0, 1), 0, (1 - clamp(k, 0, 1)) * 3), t);
            }, color);
        });
      });
    });
    if (tl.moreFolders) node(1.8, 0.6, cardTex(1.8, 0.6, { title: `+${tl.moreFolders} more folders`, bg: "#2a2008", edge: "#c9a24d" }), { kind: "Folders", title: `${tl.moreFolders} more folders`, rows: [] },
      t => (t < fil0 || t >= brk0 ? null : P((F / 2 + 0.6) * 3.15, 1.7, 0.4, 1, clamp((t - fil0) / 0.4, 0, 1))));
    if (!hasTree) node(3.6, 1.1, cardTex(3.6, 1.1, { title: tl.merged ? tl.merged.label : "No linked code change", sub: tl.entries.find(e => e.key === "changes")?.detail || "", bg: "#101c33", edge: "#6d84b5" }),
      { kind: "Code changes", title: tl.merged ? tl.merged.label : "No linked code change", rows: [["Note", tl.entries.find(e => e.key === "changes")?.detail || DASH]] },
      t => { const [a, b] = span(tl, "changes"); return t < a || t > b + 0.3 ? null : P(0, 0.4, 1, E.back((t - a) / 0.6), clamp((t - a) / 0.4, 0, 1) * clamp((b + 0.3 - t) / 0.3, 0, 1)); });
    // the merged result and the resolution stamp
    const target = hasTree || tl.merged;
    if (target) {
      const m = tl.merged || { label: "Code changes", sha: null };
      node(3.4, 1.35, cardTex(3.4, 1.35, { bg: "#0a3a26", edge: "#7cffb8", icon: "\u2714", title: m.label, sub: m.sha ? `as ${m.sha}` : (m.state === "merged" ? "merged" : "not merged yet"),
        sub2: [tl.fileCount ? `${tl.fileCount} files` : "", pm(story.totals?.added, story.totals?.deleted)].filter(Boolean).join(" \u00b7 ") }),
        { kind: "Merged result", title: m.label, rows: [["Commit", m.sha || DASH], ["State", m.state || DASH], ["Link", m.url || DASH], ["Files", String(tl.fileCount)],
          ["Lines", pm(story.totals?.added, story.totals?.deleted) || "line counts unavailable"]] },
        t => {
          const from = hasTree ? rec0 + (rec1 - rec0) * 0.7 : rA; if (t < from) return null;
          const k = E.back((t - from) / 0.55), up = E.inout((t - rA) / 0.8);
          return P(0, lerp(0.3, 0.9, up), 2.2, clamp(k, 0, 1.3) * lerp(1, 1.08, up), clamp(k * 2, 0, 1) * fade(t));
        });
    }
    node(2.7, 1.1, texture(2.7, 1.1, (g, W, H) => {
      const ok = tl.done; g.strokeStyle = ok ? "#4dff9a" : "#ffc04d"; g.lineWidth = H * 0.08; rounded(g, H * 0.08, H * 0.08, W - H * 0.16, H - H * 0.16, H * 0.18); g.stroke();
      g.fillStyle = g.strokeStyle; g.textAlign = "center"; g.font = `800 ${Math.round(H * 0.36)}px Segoe UI, sans-serif`; g.fillText(ok ? "RESOLVED" : "IN PROGRESS", W / 2, H * 0.52);
      g.font = `600 ${Math.round(H * 0.16)}px Segoe UI, sans-serif`; g.fillText(fit(g, story.resolution?.solved_by?.service ? `by ${story.resolution.solved_by.service}` : (tl.doc.status || "").replace("_", " "), W * 0.86), W / 2, H * 0.78);
    }), { kind: "Resolution", title: tl.done ? "Resolved" : `Status: ${tl.doc.status}`, rows: [["Final message", story.resolution?.final_message || DASH],
          ["Verified", story.resolution?.verified ? "yes (solver credited)" : "no solver credit"], ["Total time", fmtTime(tl.totals.time) + (tl.totals.elapsed ? " so far" : "")]] },
      t => { const at = rA + 0.5; if (t < at) return null; const k = clamp((t - at) / 0.3, 0, 1);
        return P(0.9, target ? 0.0 : -0.1, target ? 2.35 : 1.1, lerp(3, 1, E.out(k)), k * fade(t), 0, -0.14); });

    // --- overlays: banner, ledger with reels, totals
    const list = $(".rs-list"), ledger = $(".rs-ledger");
    function addEntry(e, totals) {
      const el = doc.createElement("div"); el.className = totals ? "rs-total" : "rs-entry";
      el.innerHTML = `<span class="rs-l">${esc(totals ? "Total" + (tl.totals.elapsed ? " (so far)" : "") : e.label)}${!totals && e.detail ? ` <span style="opacity:.7">\u00b7 ${esc(e.detail)}</span>` : ""}</span>${reelsHtml()}`;
      (totals ? ledger : list).append(el);
      const m = totals ? tl.totals : e.metrics;
      for (const [k] of REELS) S.reels.push({ el: el.querySelector(`[data-reel="${k}"]`), target: reelText(k, m[k]), start: S.clock, seed: S.reels.length + 1, done: false });
      while (list.children.length > (opts.full ? 12 : 4)) list.firstElementChild.remove();
    }
    function resetOverlays() { list.innerHTML = ""; ledger.querySelector(".rs-total")?.remove(); S.reels = []; S.shown.clear(); S.totalsShown = false; }
    function updateOverlays(t) {
      const tE = still && !S.playing ? Infinity : t;          // the still composition shows every entry and the totals
      tl.entries.forEach((e, i) => { if (!S.shown.has(i) && tE >= e.at) { S.shown.add(i); addEntry(e, false); } });
      if (!S.totalsShown && tE >= tl.totals.at) { S.totalsShown = true; addEntry(null, true); }
      for (const r of S.reels) {
        if (r.done) continue;
        const f = still ? reelFace(r.target, Infinity) : reelFace(r.target, (S.clock - r.start) * 1000, { seed: r.seed });
        if (r.el.textContent !== f.text) r.el.textContent = f.text;
        r.el.classList.toggle("rs-spin", !f.landed);
        r.el.classList.toggle("rs-none", f.missing);
        if (f.landed && !r.popped && !f.missing && !still) { r.popped = true; r.el.classList.add("rs-pop"); }
        if (f.landed && (!f.popping || still)) r.done = true;
      }
      const at = phaseAt(tl, t);
      if (at.index !== S.lastPhase) {
        S.lastPhase = at.index;
        const ph = at.phase, visible = tl.phases.filter(p => !p.hold), n = visible.indexOf(ph);
        $(".rs-n").textContent = ph.hold ? "" : `stage ${n + 1} / ${visible.length}`;
        $(".rs-banner b").textContent = ph.hold ? "" : ph.label; $(".rs-banner .rs-sub").textContent = ph.hold ? "" : ph.sub;
      }
    }
    // --- the detail card for a clicked node
    function showCard(n) {
      const el = $(".rs-card");
      if (!n) { el.hidden = true; el.innerHTML = ""; return; }
      const i = n.info;
      el.innerHTML = `<h4><span class="rs-kind">${esc(i.kind)}</span>${esc(i.title)}</h4><table>${(i.rows || []).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</table>
        <div class="rs-controls" style="position:static;margin-top:6px"><button type="button" data-rs="resume">Resume</button></div>`;
      el.hidden = false;
    }
    function showSummary() {
      const el = $(".rs-card");
      el.innerHTML = `<h4><span class="rs-kind">Numbers</span>${esc(`#${tl.doc.number ?? "?"} ${tl.doc.title}`)}</h4>${summaryHtml(story, esc)}<p class="rs-missing" style="color:#9fb8d8">${esc(story.prices?.note || "")}</p>
        <div class="rs-controls" style="position:static;margin-top:6px"><button type="button" data-rs="close-card">Close</button></div>`;
      el.hidden = false;
    }
    function focus(n) {
      S.focus = n || null;
      if (n) { S.playing = false; const w = n.mesh.getWorldPosition(new THREE.Vector3()); orbit.goal.copy(w); orbit.goalDist = 7.5; }
      else { orbit.goal.set(0, 0.3, 0); orbit.goalDist = 17; }
      for (const k of nodes) k.dim = !!n && k !== n;
      showCard(S.focus); playLabel(); S.dirty = true;
    }
    const playLabel = () => { $('[data-rs="play"]').textContent = S.playing ? "Pause" : "Play"; };
    // --- input: orbit, zoom, pick
    const ray = new THREE.Raycaster();
    const onDown = e => { if (e.button !== 0) return; orbit.drag = { x: e.clientX, y: e.clientY, moved: false }; try { canvas.setPointerCapture(e.pointerId); } catch {} };
    const onMove = e => { const d = orbit.drag; if (!d) return;
      orbit.yaw -= (e.clientX - d.x) * 0.006; orbit.pitch = clamp(orbit.pitch + (e.clientY - d.y) * 0.005, -0.9, 1.2);
      d.moved = d.moved || Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3; d.x = e.clientX; d.y = e.clientY; orbit.touched = S.clock; S.dirty = true; kick(); };
    const onUp = e => {
      const d = orbit.drag; orbit.drag = null; if (!d || d.moved) return;
      const b = canvas.getBoundingClientRect();
      ray.setFromCamera({ x: (e.clientX - b.left) / b.width * 2 - 1, y: -((e.clientY - b.top) / b.height) * 2 + 1 }, cam);
      const hit = ray.intersectObjects(nodes.filter(n => n.mesh.visible).map(n => n.mesh), false)[0];
      focus(hit ? hit.object.userData.node : null); if (!hit && !still) { S.playing = true; playLabel(); } kick();
    };
    const onWheel = e => { e.preventDefault(); orbit.goalDist = clamp(orbit.goalDist * (e.deltaY > 0 ? 1.1 : 0.9), 4, 60); S.dirty = true; kick(); };
    const onClick = e => {
      const b = e.target.closest && e.target.closest("[data-rs]"); if (!b) return;
      const what = b.dataset.rs;
      if (what === "play") { S.playing = !S.playing; if (S.playing) focus(null); playLabel(); }
      else if (what === "restart") { S.clock = 0; resetOverlays(); S.lastPhase = -1; S.playing = true; focus(null); }
      else if (what === "resume") { S.playing = true; focus(null); }
      else if (what === "summary") showSummary();
      else if (what === "close-card") showCard(S.focus);
      S.dirty = true; kick();
    };
    canvas.addEventListener("pointerdown", onDown); canvas.addEventListener("pointermove", onMove); canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false }); container.addEventListener("click", onClick);
    // --- off-screen and hidden-tab pause
    let io = null;
    if (env.IntersectionObserver) { io = new env.IntersectionObserver(es => { S.visible = es.some(x => x.isIntersecting); if (S.visible) kick(); }, { threshold: 0.01 }); io.observe(container); }
    const onVis = () => { if (!doc.hidden) kick(); };
    doc.addEventListener("visibilitychange", onVis);

    function pose(t) {
      for (const n of nodes) {
        const p = n.pose(t);
        if (!p || p.o <= 0.003 || p.s <= 0.003) { n.mesh.visible = false; continue; }
        n.mesh.visible = true; n.mesh.position.set(p.x, p.y, p.z); n.mesh.scale.setScalar(p.s);
        n.mesh.rotation.set(0, p.ry || 0, p.rz || 0); n.mat.opacity = p.o * (n.dim ? 0.28 : 1);
      }
    }
    function frame(now) {
      S.raf = 0;
      if (S.disposed) return;
      if (!container.isConnected) {                      // the list re-rendered without this row: give up after 2 s
        S.detachedSince = S.detachedSince || now; if (now - S.detachedSince > 2000) { api.dispose(); return; }
      } else S.detachedSince = 0;
      const dt = S.last ? Math.min(0.1, (now - S.last) / 1000) : 0; S.last = now;
      if (S.playing) { S.clock += dt; if (S.clock >= tl.length) { S.clock -= tl.length; resetOverlays(); S.lastPhase = -1; } }
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (w && h && (canvas.width !== Math.floor(w * renderer.getPixelRatio()) || canvas.height !== Math.floor(h * renderer.getPixelRatio()))) { renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }
      const o = orbit, idle = !still && !o.drag && S.clock - o.touched > 4;
      o.target.lerp(o.goal, 0.08); o.dist += (o.goalDist - o.dist) * 0.08;
      const yaw = o.yaw + (idle && S.playing ? Math.sin(now / 9000) * 0.14 : 0);
      cam.position.set(o.target.x + o.dist * Math.cos(o.pitch) * Math.sin(yaw), o.target.y + o.dist * Math.sin(o.pitch), o.target.z + o.dist * Math.cos(o.pitch) * Math.cos(yaw));
      cam.lookAt(o.target);
      const tt = still ? 0 : now / 1000;
      for (const m of waves) m.uniforms.uTime.value = tt; pMat.uniforms.uTime.value = tt;
      pose(S.clock); updateOverlays(S.clock);
      renderer.render(scene, cam); S.dirty = false;
      const settling = Math.abs(o.goalDist - o.dist) > 0.01 || o.target.distanceTo(o.goal) > 0.01 || S.reels.some(r => !r.done);
      if ((S.playing || settling || orbit.drag) && S.visible && !doc.hidden) S.raf = env.requestAnimationFrame(frame);   // paused and settled: idle until input
    }
    function kick() { if (!S.raf && !S.disposed) { S.last = 0; S.raf = env.requestAnimationFrame(frame); } }
    const api = {
      timeline: tl, state: S,
      pause() { S.playing = false; playLabel(); }, resume() { S.playing = true; focus(null); kick(); },
      focus, kick,
      dispose() {
        if (S.disposed) return; S.disposed = true;
        if (S.raf) env.cancelAnimationFrame(S.raf); S.raf = 0;
        io?.disconnect(); doc.removeEventListener("visibilitychange", onVis);
        canvas.removeEventListener("pointerdown", onDown); canvas.removeEventListener("pointermove", onMove); canvas.removeEventListener("pointerup", onUp);
        canvas.removeEventListener("wheel", onWheel); container.removeEventListener("click", onClick);
        for (const d of disposables) d.dispose?.();
        renderer.dispose(); renderer.forceContextLoss?.();
        container.innerHTML = "";
      },
    };
    kick();
    return api;
  }
  // the still composition for reduced motion: files open, hunks showing, every entry landed
  function stillTime(tl) { const [h0, h1] = span(tl, "changes", "hunks"); return h1 != null ? h1 - 0.01 : Math.max(0, tl.length - 1.8); }

  // ---------------------------------------------------------------- data, the inline disclosure, the full-size view
  const CACHE = new Map();
  async function load(id, deps) {
    const hit = CACHE.get(id);
    if (hit && Date.now() - hit.at < 20000) return hit.story;
    const r = await deps.api(`/api/requests/${encodeURIComponent(id)}/story`);
    if (!r || !r.ok) throw new Error((r && r.error) || "Could not load the request's story");
    CACHE.set(id, { at: Date.now(), story: r.data });
    while (CACHE.size > 20) CACHE.delete(CACHE.keys().next().value);
    return r.data;
  }
  // One renderer at a time: the inline panel (or the full-size view) that is open owns it.
  const ONE = { id: null, panel: null, scene: null, token: 0, full: false };
  function release() {
    ONE.token++;
    const panel = ONE.panel, wasFull = ONE.full;
    try { ONE.scene?.dispose(); } catch {}
    if (panel) {
      const details = !wasFull && panel.closest ? panel.closest("details") : null;
      panel.remove();
      if (details && details.open) details.open = false;      // its toggle(closed) finds nothing to collapse
    }
    if (wasFull) doc?.getElementById?.("reportstory")?.classList.remove("on");
    Object.assign(ONE, { id: null, panel: null, scene: null, full: false });
  }
  async function mount(id, host, deps, full) {
    ensureStyle();
    const token = ++ONE.token, panel = doc.createElement("div");
    panel.className = "rs-panel" + (full ? " rs-full" : "");
    panel.innerHTML = `<div class="rs-loading">Loading the story\u2026</div>`;
    host.append(panel);
    Object.assign(ONE, { id, panel, full });
    let story;
    try {
      story = await load(id, deps);
      if (token !== ONE.token) return null;                   // collapsed (or another opened) while loading
      await (deps.loadThree ? deps.loadThree() : null);
      if (token !== ONE.token) return null;
      if (!env.THREE && !deps.createScene) throw new Error("three.js is not available");
      ONE.scene = (deps.createScene || createScene)(panel, story, { esc: deps.esc, full, reducedMotion: deps.reducedMotion });
      return ONE.scene;
    } catch (e) {
      if (token !== ONE.token) return null;
      const esc = deps.esc || escHtml;
      panel.innerHTML = `<div class="rs-error"><div>${esc(e.message || String(e))}${story ? summaryHtml(story, esc) : ""}</div></div>`;
      return null;
    }
  }
  // the disclosure triangle opened: build the scene in its slot (a re-render of the list moves the live panel instead)
  function expand(id, slot, deps) {
    if (!id || !slot) return Promise.resolve(null);
    if (ONE.id === id && ONE.panel && !ONE.full) {
      if (ONE.panel.parentNode !== slot) slot.append(ONE.panel);
      ONE.scene?.kick?.();
      return Promise.resolve(ONE.scene);
    }
    release();
    return mount(id, slot, deps, false);
  }
  // the disclosure closed: dispose (only if it is the one that owns the renderer)
  function collapse(id) {
    if (!ONE.panel || ONE.full || (id && ONE.id !== id)) return false;
    release(); return true;
  }
  // "Detailed report": the same view, full size
  function openFull(id, deps) {
    release();
    ensureStyle();
    let el = doc.getElementById("reportstory");
    if (!el) {
      doc.body.insertAdjacentHTML("beforeend", `<div id="reportstory" role="dialog" aria-modal="true" aria-label="Detailed report">
        <div class="rs-head"><b id="rs-title">Detailed report</b>
          <button class="act" id="rs-graph" title="The older bubble graph: subtasks and the tools they used">Tool graph</button>
          <button class="act" id="rs-evidence" title="The flat report: screenshots, tasks, attempts and results">Evidence &amp; attempts</button>
          <button class="act" id="rs-close">Close</button></div><div class="rs-body"></div></div>`);
      el = doc.getElementById("reportstory");
      doc.getElementById("rs-close").onclick = () => closeFull();
      env.addEventListener?.("keydown", e => { if (e.key === "Escape" && ONE.full && !doc.querySelector("#task-evidence.on, #reportgraph.on")) closeFull(); }, true);
    }
    doc.getElementById("rs-graph").onclick = () => { const d = FULL.deps; closeFull(); d?.graph?.(FULL.id); };
    doc.getElementById("rs-evidence").onclick = () => FULL.deps?.evidence?.(FULL.id);
    FULL.id = id; FULL.deps = deps;
    el.classList.add("on");
    doc.getElementById("rs-title").textContent = "Detailed report";
    load(id, deps).then(s => { if (FULL.id === id) doc.getElementById("rs-title").textContent = `Detailed report \u00b7 #${s.request?.number ?? "?"} ${s.request?.title || ""}`; }).catch(() => {});
    deps.onChange?.();
    return mount(id, el.querySelector(".rs-body"), deps, true);
  }
  const FULL = { id: null, deps: null };
  function closeFull() {
    if (ONE.full) release();
    doc.getElementById("reportstory")?.classList.remove("on");
    const d = FULL.deps; FULL.id = null; d?.onChange?.();
  }
  const isFullOpen = () => !!doc?.getElementById?.("reportstory")?.classList.contains("on");
  // the disclosure markup for one request row (summary text is stable: the inbox keeps it open across re-renders)
  const disclosureHtml = id => `<details class="rs-disclosure" data-story="${escHtml(id)}"><summary>Detailed report</summary><div class="rs-slot"></div></details>`;
  // after the list re-rendered its HTML: put the live panel into the new row's slot at once (no flash, no rebuild)
  function reattach(host) {
    if (!ONE.panel || ONE.full || !ONE.id || !host) return false;
    const d = [...host.querySelectorAll("details.rs-disclosure")].find(x => x.dataset.story === ONE.id);
    if (!d || !d.open) return false;
    const slot = d.querySelector(".rs-slot");
    if (slot && ONE.panel.parentNode !== slot) slot.append(ONE.panel);
    ONE.scene?.kick?.();
    return true;
  }
  // wire a list host: details toggles drive expand/collapse
  function bind(host, deps) {
    host.addEventListener("toggle", e => {
      const d = e.target; if (!d || !d.matches || !d.matches("details.rs-disclosure")) return;
      const id = d.dataset.story;
      if (d.open) expand(id, d.querySelector(".rs-slot"), typeof deps === "function" ? deps() : deps);
      else collapse(id);
    }, true);
  }
  return { LIMITS, DASH, fmtTokens, fmtCost, fmtTime, reelText, reelFace, foldersOf, timeline, phaseAt, span, summaryHtml, stillTime, reattach,
           createScene, load, expand, collapse, openFull, closeFull, isFullOpen, disclosureHtml, bind, state: ONE, cache: CACHE, CSS };
});
