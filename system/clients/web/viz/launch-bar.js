/* Launch bar (#1635): a full-width loading bar along the bottom edge, just above the status strip, while a game launch
   runs (launch_game / session_swap: mod fetch, staging, emulator start) from any path: Library Play, Mods Play, Special
   builds, notification Play, swaps. It reads the job feed the status strip already polls (GET /api/jobs?state=queued,running)
   and the job records jobWait already fetches; it never polls on its own. When a launch leaves the feed it asks for that
   one job once to learn how it ended.
   - determinate when the job reports a percent or an "x/y MB" counter (finer progress inside a stage), else a sweep
   - the fill runs red (0%) -> green (33%) -> blue (66%) -> white (100%), interpolated by progress
   - the job's console lines scroll across it right to left, newest appended; hover pauses; reduced motion shows the
     latest line still
   - success fades out; failure turns it into a red line with the reason (click for details, x closes)
   Desktop app: ../web/viz/launch-bar.js. Node tests load the factory (tests/test_launch_bar.cjs). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.GBoxLaunchBar = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const doc = env && env.document;
  const LAUNCH_TOOLS = new Set(["launch_game", "session_swap"]);
  const LIVE = new Set(["queued", "running"]);
  const STOPS = [[0, [229, 38, 38]], [33, [34, 197, 94]], [66, [47, 107, 255]], [100, [255, 255, 255]]];
  const DONE_MS = 1400, FADE_MS = 650, ERROR_MS = 60000, OBSERVED_GRACE_MS = 5000;
  const clamp = (v, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));
  const finite = v => typeof v === "number" && Number.isFinite(v);

  // ---- colour: red -> green -> blue -> white as the bar grows ---------------------------------------------------
  function colorAt(pct) {
    const p = clamp(finite(pct) ? pct : 0);
    for (let i = 1; i < STOPS.length; i++) {
      const [p0, c0] = STOPS[i - 1], [p1, c1] = STOPS[i];
      if (p <= p1) { const t = (p - p0) / (p1 - p0); return c0.map((v, k) => Math.round(v + (c1[k] - v) * t)); }
    }
    return STOPS[STOPS.length - 1][1].slice();
  }
  const rgb = c => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  // The fill covers 0..pct of the spectrum: red at its left end, every colour it passed, the current colour at its edge.
  function fillGradient(pct) {
    const p = clamp(finite(pct) ? pct : 0);
    if (p <= 0) return rgb(colorAt(0));
    const stops = STOPS.filter(([s]) => s < p).map(([s, c]) => `${rgb(c)} ${(100 * s / p).toFixed(1)}%`);
    return `linear-gradient(90deg, ${stops.join(", ")}, ${rgb(colorAt(p))} 100%)`;
  }

  // ---- progress: the job's percent, refined by an "x/y MB" counter inside a known stage -------------------------
  const UNIT = { b: 1 / 2 ** 20, kb: 1 / 1024, kib: 1 / 1024, mb: 1, mib: 1, gb: 1024, gib: 1024, tb: 2 ** 20, tib: 2 ** 20 };
  const num = s => Number(String(s).replace(/,/g, ""));
  function fraction(msg) {
    const m = /(\d[\d,]*(?:\.\d+)?)\s*([KMGT]i?B)?\s*\/\s*(\d[\d,]*(?:\.\d+)?)\s*([KMGT]i?B)\b/i.exec(String(msg || ""));
    if (!m) return null;
    const total = num(m[3]) * UNIT[m[4].toLowerCase()], done = num(m[1]) * UNIT[(m[2] || m[4]).toLowerCase()];
    if (!(total > 0) || !(done >= 0)) return null;
    return { done, total, f: clamp(done / total, 0, 1) };
  }
  // Where the launch tools put these stages (the worker rounds the percent; the counter is exact).
  const STAGES = [
    { rx: /^Fetching mod .+ from the collection/i, from: 20, to: 28 },   // gbox/filemods.stage: 20 + 8 * done / total
    { rx: /^Staging /i, from: 30, to: 70 },                               // gbox/tools._stage_for_launch: 30 + 40 * done / total
  ];
  const messageOf = job => { const p = job && job.progress; return String((p && typeof p === "object" ? p.msg : p) || ""); };
  function progressOf(job) {
    const p = job && job.progress, msg = messageOf(job);
    let pct = p && typeof p === "object" && finite(p.pct) ? clamp(p.pct) : null;
    const f = fraction(msg);
    if (f) {
      const band = STAGES.find(s => s.rx.test(msg));
      if (band && (pct === null || (pct >= band.from - 1 && pct <= band.to + 1)))
        pct = Math.max(pct === null ? 0 : pct, band.from + (band.to - band.from) * f.f);
      else if (pct === null) pct = 100 * f.f;
    }
    return { pct, determinate: pct !== null, fraction: f };
  }

  // ---- console lines: the job's progress log, a ticking counter collapsed to its newest value -------------------
  const clean = s => String(s == null ? "" : s).replace(/\x1b\[[0-9;]*[A-Za-z]/g, "").replace(/\s+/g, " ").trim();
  const keyOf = s => clean(s).replace(/\d[\d,.]*/g, "#");
  function linesOf(job) {
    const log = Array.isArray(job && job.progress_log) ? job.progress_log : [];
    const raw = log.map(clean).filter(Boolean), msg = clean(messageOf(job));
    if (msg && raw[raw.length - 1] !== msg) raw.push(msg);
    const out = [];
    for (const l of raw) { if (out.length && keyOf(out[out.length - 1]) === keyOf(l)) out[out.length - 1] = l; else out.push(l); }
    return out;
  }

  // ---- which jobs are launches, and of which game ---------------------------------------------------------------
  const isLaunch = job => !!job && LAUNCH_TOOLS.has(job.tool);
  function gameOf(job) {
    const i = (job && job.input) || {}, g = i.game && typeof i.game === "object" ? i.game : {};
    // mod: the operator's name for the build when it has one (the server puts mod_title on the launch), else its folder
    return { id: String(i.game_id || g.game_id || g.id || ""), title: String(g.title || i.title || ""), mod: String(i.mod_title || i.mod || "") };
  }
  const startedAt = j => j.created || j.started || 0;
  const activityAt = j => (j.progress && typeof j.progress === "object" && j.progress.ts) || j.started || j.created || 0;

  // ---- model: live launches grouped per game (a swap and the launch it starts are one), outcome, new lines --------
  function createModel({ fetchJob = null, now = () => Date.now(), onChange = () => {} } = {}) {
    const live = new Map(), observedAt = new Map(), settling = new Set(), finished = new Set();
    const emitted = new Map(), peak = new Map(), dismissed = new Set();
    let outcome = null;
    const groupKey = j => gameOf(j).id || j.id;

    function track(j) {
      if (!live.has(j.id)) outcome = null;                                   // a new launch replaces the last outcome
      live.set(j.id, j);
    }
    function groups() {
      const by = new Map();
      for (const j of live.values()) { const k = groupKey(j); if (!by.has(k)) by.set(k, []); by.get(k).push(j); }
      return [...by.entries()].map(([key, jobs]) => ({ key, jobs: jobs.sort((a, b) => startedAt(a) - startedAt(b)) }))
        .sort((a, b) => Math.max(...b.jobs.map(startedAt)) - Math.max(...a.jobs.map(startedAt))
                     || Math.max(...b.jobs.map(activityAt)) - Math.max(...a.jobs.map(activityAt)));
    }
    function groupTitle(g) {
      const jobs = g.jobs, swap = jobs.find(j => j.tool === "session_swap");
      const named = jobs.map(gameOf).find(x => x.title) || gameOf(jobs[0]);
      const name = named.title || named.id || "the game";
      const mod = (swap ? gameOf(swap).mod : "") || jobs.map(gameOf).map(x => x.mod).find(Boolean) || "";
      return (swap ? "Swapping " : "Launching ") + name + (mod ? ` · ${mod}` : "");
    }
    // A swap that starts a launch: the launch's progress fills what is left of the swap's.
    function groupProgress(g) {
      const swap = g.jobs.find(j => j.tool === "session_swap"), child = g.jobs.filter(j => j !== swap).pop();
      const a = swap ? progressOf(swap) : null, b = child ? progressOf(child) : null;
      let pct;
      if (a && b) pct = a.pct === null ? b.pct : b.pct === null ? a.pct : a.pct + (100 - a.pct) * b.pct / 100;
      else pct = (a || b).pct;
      const frac = (b && b.fraction) || (a && a.fraction) || null;
      if (pct === null) return { pct: null, determinate: false, fraction: frac };
      const top = Math.max(peak.get(g.key) || 0, clamp(pct));                 // never runs backwards within one launch
      peak.set(g.key, top);
      return { pct: top, determinate: true, fraction: frac };
    }
    function remote(list) {
      const ids = new Set();
      for (const j of list || []) if (isLaunch(j) && LIVE.has(j.state) && !finished.has(j.id)) { ids.add(j.id); track(j); }
      for (const id of [...live.keys()]) {
        if (ids.has(id) || settling.has(id)) continue;
        if (observedAt.has(id) && now() - observedAt.get(id) < OBSERVED_GRACE_MS) continue;   // jobWait follows it and brings the end
        settle(id, null);
      }
      onChange();
    }
    function observe(j) {
      if (!isLaunch(j) || !j.id || finished.has(j.id)) return;
      observedAt.set(j.id, now());
      if (LIVE.has(j.state)) { track(j); onChange(); return; }
      if (!live.has(j.id)) track(j);
      return settle(j.id, j);
    }
    async function settle(id, final) {
      if (settling.has(id)) return; settling.add(id);
      let fin = final;
      try { if (!fin && fetchJob) fin = await fetchJob(id); } catch { fin = null; }
      settling.delete(id);
      const last = live.get(id);
      if (!last) return;
      if (fin && LIVE.has(fin.state)) { track(fin); onChange(); return; }    // the feed was older than the job: still running
      const key = groupKey(last), g = groups().find(x => x.key === key), title = g ? groupTitle(g) : "Launching the game";
      live.delete(id); finished.add(id); emitted.delete(id); observedAt.delete(id);
      if (finished.size > 300) finished.delete(finished.values().next().value);
      if ([...live.values()].some(j => groupKey(j) === key)) { onChange(); return; }   // the rest of this launch is still going
      peak.delete(key); dismissed.delete(key);
      const job = fin || last, state = fin ? fin.state : "gone";
      if (state === "failed") outcome = { kind: "error", job, title, reason: clean(fin.error) || "the launch failed", at: now() };
      else if (state === "succeeded" && !live.size) outcome = { kind: "done", job, title, at: now() };
      else if (!live.size) outcome = null;
      onChange();
    }
    function view() {
      const gs = groups().filter(g => !dismissed.has(g.key));
      if (outcome && outcome.kind === "error" && now() - outcome.at < ERROR_MS)
        return { state: "error", title: outcome.title.replace(/^(Launching|Swapping) /, ""), reason: outcome.reason, job: outcome.job,
                 pct: 100, determinate: true, lines: [outcome.reason], count: gs.length + 1 };
      if (gs.length) {
        const g = gs[0], prog = groupProgress(g), lines = [].concat(...g.jobs.map(linesOf));
        const job = g.jobs.slice().sort((a, b) => activityAt(b) - activityAt(a))[0];
        if (!lines.length) lines.push(g.jobs.every(j => j.state === "queued") ? "Waiting for a free PC…" : "Starting…");
        return { state: "running", title: groupTitle(g), key: g.key, job, pct: prog.pct, determinate: prog.determinate,
                 fraction: prog.fraction, lines, count: gs.length };
      }
      if (outcome && outcome.kind === "done" && now() - outcome.at < DONE_MS + FADE_MS)
        return { state: "done", title: outcome.title, job: outcome.job, pct: 100, determinate: true, lines: ["Started"], count: 1 };
      return { state: "hidden", count: 0, lines: [] };
    }
    // New console lines of the launch on show since the last call; {replace} = a counter that ticked (same line, new numbers).
    function drain() {
      const v = view(); if (v.state !== "running") return [];
      const g = groups().find(x => x.key === v.key), out = [];
      for (const j of g.jobs) {
        const L = linesOf(j); if (!L.length) continue;
        const last = emitted.get(j.id);
        if (last === undefined) out.push(...L.slice(-2).map(text => ({ text, replace: false })));
        else {
          let i = L.lastIndexOf(last);
          if (i < 0) {
            for (let k = L.length - 1; k >= 0; k--) if (keyOf(L[k]) === keyOf(last)) { i = k; out.push({ text: L[k], replace: true }); break; }
            if (i < 0) { out.push(...L.slice(-2).map(text => ({ text, replace: false }))); i = L.length - 1; }
          }
          out.push(...L.slice(i + 1).map(text => ({ text, replace: false })));
        }
        emitted.set(j.id, L[L.length - 1]);
      }
      return out;
    }
    function dismiss() {
      if (outcome) { outcome = null; return; }
      const v = view(); if (v.state === "running") dismissed.add(v.key);
    }
    const clearOutcome = kind => { if (outcome && (!kind || outcome.kind === kind)) outcome = null; };
    return { remote, observe, view, drain, dismiss, clearOutcome, get outcome() { return outcome; }, live };
  }

  // ---- the bar ----------------------------------------------------------------------------------------------------
  const OUTLINE = "0 0 2px #000, 1px 1px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000";
  const CSS = `
#launchbar { position:fixed; left:0; right:0; bottom:var(--lb-bottom,28px); height:18px; z-index:59; display:none; overflow:hidden;
  background:rgba(13,14,18,.88); border-top:1px solid rgba(255,255,255,.14); color:#fff; cursor:pointer; user-select:none;
  font:600 11px/18px "Segoe UI", system-ui, sans-serif; opacity:1; transition:opacity ${FADE_MS}ms ease; contain:layout paint; }
#launchbar.on { display:block; } #launchbar.fade { opacity:0; }
#launchbar .lb-fill { position:absolute; left:0; top:0; bottom:0; width:0; transition:width .5s ease, box-shadow .5s ease; }
#launchbar .lb-sweep { position:absolute; inset:0; display:none; opacity:.85; background:linear-gradient(90deg, transparent 0,
  rgb(229,38,38) 20%, rgb(34,197,94) 45%, rgb(47,107,255) 70%, #fff 90%, transparent 100%) no-repeat; background-size:35% 100%;
  animation:lb-sweep 1.8s linear infinite; }
#launchbar.ind .lb-sweep { display:block; } #launchbar.ind .lb-fill { display:none; }
@keyframes lb-sweep { from { background-position:-60% 0; } to { background-position:160% 0; } }
#launchbar .lb-row { position:absolute; inset:0; display:flex; align-items:center; gap:8px; padding:0 2px 0 10px; text-shadow:${OUTLINE}; }
#launchbar .lb-title { flex:none; max-width:32%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#launchbar .lb-view { position:relative; flex:1; min-width:0; height:100%; overflow:hidden; }
#launchbar .lb-track { position:absolute; left:0; top:0; white-space:nowrap; will-change:transform; }
#launchbar .lb-line { display:inline-block; padding-right:3em; font-weight:500; }
#launchbar .lb-line::before { content:"\\203A  "; opacity:.85; }
#launchbar .lb-static { display:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500; }
#launchbar.still .lb-track { display:none; } #launchbar.still .lb-static { display:block; }
#launchbar .lb-pct { flex:none; font-variant-numeric:tabular-nums; }
#launchbar .lb-count { flex:none; background:rgba(0,0,0,.6); border-radius:8px; padding:0 6px; line-height:14px; }
#launchbar .lb-x { flex:none; background:none; border:0; color:#fff; cursor:pointer; font:16px/16px sans-serif; padding:0 6px; text-shadow:${OUTLINE}; }
#launchbar.err { background:#7f1d1d; } #launchbar.err .lb-fill { width:100% !important; background:#b91c1c !important; box-shadow:none !important; }
#launchbar.done .lb-fill { width:100% !important; }
@media (prefers-reduced-motion: reduce) {
  #launchbar .lb-sweep { animation:none; background-size:100% 100%; background-position:0 0; opacity:.45; }
  #launchbar .lb-fill, #launchbar { transition:none; }
}`;

  function mount(opts = {}) {
    if (!doc) throw new Error("the launch bar needs a document");
    const later = opts.setTimeout || ((fn, ms) => env.setTimeout(fn, ms)), cancel = opts.clearTimeout || (t => env.clearTimeout(t));
    const raf = "raf" in opts ? opts.raf : (env.requestAnimationFrame ? fn => env.requestAnimationFrame(fn) : null);
    const model = createModel({ fetchJob: opts.fetchJob, now: opts.now, onChange: () => render() });
    if (!doc.getElementById("gbox-launchbar-css")) {
      const style = doc.createElement("style"); style.id = "gbox-launchbar-css"; style.textContent = CSS; doc.head.appendChild(style);
    }
    const part = (tag, cls, parent) => { const e = doc.createElement(tag); e.className = cls; parent.appendChild(e); return e; };
    const el = doc.createElement("div"); el.id = "launchbar";
    el.setAttribute("role", "progressbar"); el.setAttribute("aria-label", "Game launch progress");
    el.setAttribute("aria-valuemin", "0"); el.setAttribute("aria-valuemax", "100");
    if (opts.bottom != null) el.style.setProperty("--lb-bottom", typeof opts.bottom === "number" ? opts.bottom + "px" : String(opts.bottom));
    const fill = part("div", "lb-fill", el); part("div", "lb-sweep", el);
    const row = part("div", "lb-row", el), title = part("span", "lb-title", row), view = part("span", "lb-view", row);
    const track = part("span", "lb-track", view), still = part("span", "lb-static", view);
    const pctEl = part("span", "lb-pct", row), count = part("span", "lb-count", row), close = part("button", "lb-x", row);
    close.type = "button"; close.textContent = "×"; close.title = "Hide this bar (the launch keeps going)";
    close.setAttribute("aria-label", "Hide the launch bar");
    (opts.host || doc.body).appendChild(el);

    let reduced = false, cls = "", current = { state: "hidden" }, outcomeShown = null, timers = [], latest = "";
    try {
      const mql = env.matchMedia && env.matchMedia("(prefers-reduced-motion: reduce)");
      reduced = !!(mql && mql.matches);
      if (mql && mql.addEventListener) mql.addEventListener("change", e => { reduced = !!e.matches; render(); });
    } catch { reduced = false; }
    if ("reducedMotion" in opts) reduced = !!opts.reducedMotion;

    // ---- marquee: spans on a track moving left; new lines join at the right ----
    const mq = { x: 0, paused: false, raf: 0, last: 0 };
    const kids = () => Array.from(track.children);
    const width = e => e.offsetWidth || 0;
    const viewWidth = () => view.clientWidth || view.offsetWidth || 0;
    const trackWidth = () => kids().reduce((w, k) => w + width(k), 0);
    function addSpan(text) {
      const vw = viewWidth();
      if (!track.children.length) mq.x = vw;
      const right = mq.x + trackWidth(), span = part("span", "lb-line", track);
      span.textContent = text;
      if (right < vw) span.style.paddingLeft = Math.round(vw - right) + "px";       // enter at the right edge, not mid-bar
      // a burst of lines: keep the newest few that have not come into view yet
      let x = mq.x; const waiting = [];
      for (const k of kids()) { if (x > vw) waiting.push(k); x += width(k); }
      while (waiting.length > 3) track.removeChild(waiting.shift());
      return span;
    }
    function push(text, replace) {
      latest = text;
      const all = kids(), last = all[all.length - 1];
      if (replace && last && keyOf(last.textContent) === keyOf(text)) { last.textContent = text; return; }
      addSpan(text);
    }
    function waitingCount() { let x = mq.x, n = 0; const vw = viewWidth(); for (const k of kids()) { if (x > vw) n++; x += width(k); } return n; }
    const speed = () => Math.min(220, 60 + 40 * waitingCount());      // px/s: catch up when lines queue
    function tick(dt) {
      if (current.state !== "running" || reduced || mq.paused) return false;
      mq.x -= speed() * dt / 1000;
      let first = track.children[0];
      while (first && mq.x + width(first) <= 0) { mq.x += width(first); track.removeChild(first); first = track.children[0]; }
      if (latest && mq.x + trackWidth() < viewWidth() * 0.35) addSpan(latest);    // all read: the latest line comes round again
      track.style.transform = `translateX(${Math.round(mq.x)}px)`;
      return true;
    }
    const moving = () => !!raf && current.state === "running" && !reduced && !mq.paused;
    function loop(t) {
      mq.raf = 0;
      if (!moving()) { mq.last = 0; return; }
      const dt = mq.last ? Math.min(100, t - mq.last) : 16; mq.last = t;
      tick(dt); mq.raf = raf(loop);
    }
    function kick() { if (!mq.raf && moving()) { mq.last = 0; mq.raf = raf(loop); } }
    function clearTrack() { for (const k of kids()) track.removeChild(k); mq.x = 0; latest = ""; track.style.transform = "translateX(0px)"; }

    function setClass(next) { if (next !== cls) { cls = next; el.className = next; } }
    function schedule(fn, ms) { const t = later(fn, ms); timers.push(t); return t; }
    function render() {
      const v = model.view(), was = current.state; current = v;
      if (v.state !== "done" && v.state !== "error") outcomeShown = null;
      if (v.state === "hidden") { setClass(""); clearTrack(); return; }
      const flags = ["on"];
      if (v.state === "running" && !v.determinate) flags.push("ind");
      if (reduced || v.state !== "running") flags.push("still");
      if (v.state === "error") flags.push("err");
      if (v.state === "done") flags.push("done");
      if (v.state === "done" && outcomeShown === model.outcome && / fade$/.test(cls)) flags.push("fade");
      setClass(flags.join(" "));
      const pct = v.determinate ? v.pct : null;
      fill.style.width = pct === null ? "0%" : pct.toFixed(1) + "%";
      fill.style.background = fillGradient(pct === null ? 0 : pct);
      fill.style.boxShadow = pct === null ? "none" : `0 0 10px ${rgb(colorAt(pct))}`;
      if (pct === null) el.removeAttribute("aria-valuenow"); else el.setAttribute("aria-valuenow", String(Math.round(pct)));
      pctEl.textContent = v.state === "running" && pct !== null ? Math.round(pct) + "%" : v.state === "done" ? "100%" : "";
      count.textContent = v.count > 1 ? (v.state === "error" ? `+${v.count - 1} running` : `+${v.count - 1}`) : "";
      count.style.display = v.count > 1 ? "" : "none";
      count.title = v.count > 1 ? `${v.count} launches in progress; showing the newest` : "";
      if (v.state === "running") {
        title.textContent = v.title;
        if (was !== "running") clearTrack();
        for (const l of model.drain()) push(l.text, l.replace);
        still.textContent = v.lines[v.lines.length - 1] || "";
        el.title = `${v.title}: ${still.textContent}${pct === null ? "" : ` (${Math.round(pct)}%)`} · hover pauses · click for details`;
        el.setAttribute("aria-valuetext", el.title);
        kick();
      } else if (v.state === "done") {
        title.textContent = "✓ " + v.title.replace(/^(Launching|Swapping) /, "");
        still.textContent = "Started"; el.title = title.textContent + " started";
        if (outcomeShown !== model.outcome) {
          outcomeShown = model.outcome; const mine = outcomeShown;
          schedule(() => { if (model.outcome === mine) setClass(cls + " fade"); }, DONE_MS);
          schedule(() => { if (model.outcome === mine) { model.clearOutcome("done"); render(); } }, DONE_MS + FADE_MS);
        }
      } else if (v.state === "error") {
        title.textContent = "✕ Launch failed: " + v.title;
        still.textContent = v.reason; el.title = `${title.textContent}: ${v.reason} · click for details · × closes`;
        el.setAttribute("aria-valuetext", el.title);
        if (outcomeShown !== model.outcome) {
          outcomeShown = model.outcome; const mine = outcomeShown;
          schedule(() => { if (model.outcome === mine) { model.clearOutcome("error"); render(); } }, ERROR_MS);
        }
      }
    }
    el.addEventListener("mouseenter", () => { mq.paused = true; });
    el.addEventListener("mouseleave", () => { mq.paused = false; kick(); });
    el.addEventListener("click", e => {
      if (e && e.target === close) { if (e.stopPropagation) e.stopPropagation(); model.dismiss(); render(); return; }
      if (current.job && opts.onDetails) opts.onDetails(current.job, current);
    });
    return {
      el, model,
      remote: jobs => model.remote(jobs),
      observe: job => model.observe(job),
      dismiss: () => { model.dismiss(); render(); },
      view: () => model.view(),
      render, tick,
      dispose() { for (const t of timers) cancel(t); timers = []; mq.raf = 0; if (el.parentNode) el.parentNode.removeChild(el); },
    };
  }

  return { mount, createModel, colorAt, rgb, fillGradient, fraction, progressOf, linesOf, isLaunch, gameOf, keyOf, STOPS };
});
