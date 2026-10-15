/* Ghost runs (#1098, gbox/ghost_runs.py, docs/ghost-runs.md): the Runs panel in the session view and the ghosts drawn
   over the live game picture.

   Data      GET  /api/ghosts/game/{gid}        runs (times, splits, best flags), level bests, prefs, the runs to show
             GET  /api/ghosts/runs/{rid}        one run with its per-frame track (columns f, x, y, lv, ap, face, ...)
             GET  /api/ghosts/live/{sid}        the live player: level, level / run frame, camera (scr), ~15 updates/s
             POST /api/ghosts/game/{gid}/prefs  pick (best | last | pb_segments | custom | none), shown, colors, mode,
                                                hud, me, picture;  PATCH / DELETE /api/ghosts/runs/{rid}  rename / delete
   Overlay   a click-through canvas over the game picture (the stream <img id=scr> or the GPU compositor's <video> in
             #nativeslot). A ghost's screen position = its world x minus the LIVE camera (projection), its y as recorded
             (SMB1 never scrolls vertically); native pixels map onto the picture through its aspect (4:3, 8:7 pixels,
             square pixels, fill) or Auto (the candidate whose predicted box around the live player stands out most).
   Sync      level: the ghost is as far into the same level as you are (its clearing attempt); run: the same time since
             the run started, shown while the ghost is on your level and map.
   The pure functions (ghostFrame, sampleAt, ghostScreen, pictureRect, fmtTime, raceRows, aspectScore) are exported for
   tests/test_ghost_runs_ui.cjs. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(null);
  else root.GhostRuns = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const FIELDS = ["f", "x", "y", "lv", "ap", "face", "st", "anim", "pw", "joy", "scr", "sub"];
  const ASPECTS = { "4:3": 4 / 3, "8:7": 256 * 8 / 7 / 240, "1:1": 256 / 240 };
  const AUTO_CANDIDATES = ["4:3", "8:7", "1:1", "fill"];
  const levelName = lv => `${(lv >> 2) + 1}-${(lv & 3) + 1}`;

  // ------------------------------------------------------------------------------------------------ pure functions
  function ghostFrame(run, live, mode) {
    if (mode === "run") return live.run_frame ?? null;
    const lf = live.level_frame, lvl = live.attempt_level || live.level;
    if (lf == null) return null;
    const a = pickAttempt(run, lvl);
    return a ? a.start + lf : null;
  }
  function pickAttempt(run, lvl) {                // its clearing try, else its longest try on that level
    const tries = (run.attempts || []).filter(a => a.level === lvl);
    if (!tries.length) return null;
    return [...tries].reverse().find(t => t.result === "clear") || tries.reduce((b, t) => (t.end - t.start > b.end - b.start ? t : b));
  }
  function attemptOf(run, live, mode) {           // the ghost attempt a level-synced ghost replays (its end = finish)
    return mode === "run" ? null : pickAttempt(run, live.attempt_level || live.level);
  }
  function sampleAt(cols, frame, maxGap = 8) {
    const fs = cols.f;
    if (!fs || !fs.length || frame == null || frame < fs[0]) return null;
    let lo = 0, hi = fs.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (fs[mid] <= frame) lo = mid; else hi = mid - 1; }
    const i = lo, row = {};
    for (const k of FIELDS) row[k] = cols[k][i];
    row.done = i === fs.length - 1 && frame > fs[i];
    const j = i + 1;
    if (j < fs.length && fs[j] - fs[i] > 0 && fs[j] - fs[i] <= maxGap && frame > fs[i] && cols.lv[j] === row.lv && cols.ap[j] === row.ap) {
      const t = (frame - fs[i]) / (fs[j] - fs[i]);
      row.x += (cols.x[j] - row.x) * t; row.y += (cols.y[j] - row.y) * t;
    }
    return row;
  }
  function ghostScreen(row, live, profile) {
    if (!row || levelName(row.lv) !== live.level || row.ap !== live.ap) return null;
    const box = profile?.box || { w: 16, h: 32, small_h: 16 }, w = (profile?.screen || [256, 240])[0];
    const small = !!(row.pw & 4), h = small ? box.small_h : box.h;
    const sx = row.x - live.scr, yHi = Math.floor(row.y / 256), y = row.y - 256;
    const out = { x: sx, y: y + (box.h - h), w: box.w, h, small, face: row.face, visible: yHi === 1, anim: row.anim };
    if (sx + box.w < 0) { out.side = "left"; out.distance = -sx; }
    else if (sx > w) { out.side = "right"; out.distance = sx - w; }
    return out;
  }
  // The game picture inside an element: the frame fitted (object-fit: contain), then the native picture of the given
  // aspect fitted inside the frame (the emulator letterboxes), cropTop / cropBottom native lines hidden.
  function pictureRect(box, natural, picture, screen) {
    const [sw, sh] = screen || [256, 240];
    const s = Math.min(box.w / natural.w, box.h / natural.h);
    const fw = natural.w * s, fh = natural.h * s, fx = box.x + (box.w - fw) / 2, fy = box.y + (box.h - fh) / 2;
    const ct = +(picture?.crop_top || 0), cb = +(picture?.crop_bottom || 0), lines = sh - ct - cb;
    const asp = picture?.aspect === "fill" ? fw / fh : (ASPECTS[picture?.aspect] || ASPECTS["4:3"]) * sh / lines;
    let pw = fw, ph = fw / asp;
    if (ph > fh) { ph = fh; pw = fh * asp; }
    const r = { x: fx + (fw - pw) / 2, y: fy + (fh - ph) / 2, w: pw, h: ph };
    return { ...r, sx: pw / sw, sy: ph / lines, top: ct,
      map: (nx, ny) => [r.x + nx * pw / sw, r.y + (ny - ct) * ph / lines] };
  }
  function fmtTime(frames, fps = 60.0988) {
    if (frames == null || !isFinite(frames)) return "–";
    const neg = frames < 0, t = Math.abs(frames) / fps, m = Math.floor(t / 60), s = t - m * 60;
    return (neg ? "−" : "") + (m ? `${m}:${s.toFixed(2).padStart(5, "0")}` : s.toFixed(2));
  }
  function fmtDelta(frames, fps) { return frames == null ? "" : (frames > 0 ? "+" : frames < 0 ? "" : "±") + fmtTime(frames, fps); }
  // Race rows against one ghost: every split you finished (delta = yours - ghost's, by level) and the level you're on.
  function raceRows(live, ghost, fps = 60.0988) {
    const theirs = Object.fromEntries((ghost?.splits || []).map(s => [s.level, s]));
    const rows = (live.splits || []).map(s => ({ level: s.level, live: s.frames, ghost: theirs[s.level]?.frames ?? null,
      delta: theirs[s.level] ? s.frames - theirs[s.level].frames : null, done: true }));
    if (live.attempt_level && !rows.some(r => r.level === live.attempt_level)) {
      const g = theirs[live.attempt_level];
      rows.push({ level: live.attempt_level, live: live.level_frame, ghost: g?.segment ?? null, delta: null, done: false });
    }
    return rows.map(r => ({ ...r, text: `${r.level} ${fmtTime(r.live, fps)}${r.delta != null ? " " + fmtDelta(r.delta, fps) : r.ghost != null ? " / " + fmtTime(r.ghost, fps) : ""}` }));
  }
  // Auto picture: how much the predicted player box stands out from the ring around it (higher = the box is on the
  // player). px(x, y) -> [r, g, b] in picture-frame pixels; rect = pictureRect(...) in those same pixels.
  function aspectScore(px, rect, live, profile) {
    const box = profile?.box || { w: 16, h: 32, small_h: 16 };
    const h = live.small ? box.small_h : box.h, top = live.rely + 1 + (box.h - h), left = live.relx;
    const sample = (x0, y0, x1, y1, step) => { const out = [];
      for (let y = y0; y < y1; y += step) for (let x = x0; x < x1; x += step) { const [cx, cy] = rect.map(x, y); out.push(px(Math.round(cx), Math.round(cy))); }
      return out; };
    const inside = sample(left + 2, top + 2, left + box.w - 2, top + h - 2, 2);
    const ring = [...sample(left - 8, top - 6, left - 2, top + h, 3), ...sample(left + box.w + 2, top - 6, left + box.w + 8, top + h, 3)];
    if (!inside.length || !ring.length) return 0;
    const mean = a => a.reduce((s, p) => [s[0] + p[0], s[1] + p[1], s[2] + p[2]], [0, 0, 0]).map(v => v / a.length);
    const rm = mean(ring), dist = p => Math.abs(p[0] - rm[0]) + Math.abs(p[1] - rm[1]) + Math.abs(p[2] - rm[2]);
    const ringSpread = ring.reduce((s, p) => s + dist(p), 0) / ring.length;
    return inside.filter(p => dist(p) > 60).length / inside.length - Math.min(0.5, ringSpread / 400);
  }

  // ------------------------------------------------------------------------------------------------ drawing
  function figure(ctx, g, rect, color, alpha, label) {
    const [x, y] = rect.map(g.x, g.y + 1), w = g.w * rect.sx, h = g.h * rect.sy, u = w / 16;
    ctx.save(); ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.strokeStyle = color;
    if (g.face === 2) { ctx.translate(x + w, y); ctx.scale(-1, 1); } else ctx.translate(x, y);   // face left = mirror
    const big = !g.small, step = (g.anim >> 3) & 1;
    const head = big ? h * 0.28 : h * 0.42, body = big ? h * 0.42 : h * 0.3, legs = h - head - body;
    ctx.fillRect(3 * u, 0, 9 * u, head * 0.35);                                // cap
    ctx.fillRect(9 * u, head * 0.25, 5 * u, head * 0.14);                      // brim
    ctx.beginPath(); ctx.ellipse(8 * u, head * 0.62, 5 * u, head * 0.38, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillRect(3 * u, head, 10 * u, body);                                  // body
    ctx.fillRect(step ? 1 * u : 3 * u, head + body, 4 * u, legs);             // legs (apart when running)
    ctx.fillRect(step ? 11 * u : 9 * u, head + body, 4 * u, legs);
    ctx.restore();
    if (label) { ctx.save(); ctx.globalAlpha = Math.min(1, alpha + 0.3); ctx.font = `bold ${Math.max(10, 7 * rect.sx)}px ui-monospace,Consolas,monospace`;
      ctx.fillStyle = color; ctx.textAlign = "center"; ctx.fillText(label, x + w / 2, y - 3); ctx.restore(); }
  }
  function edgeArrow(ctx, g, rect, color, label) {
    const [, y] = rect.map(0, Math.max(16, Math.min(220, g.y + g.h / 2)));
    const left = g.side === "left", x = left ? rect.x + 4 : rect.x + rect.w - 4, d = left ? 1 : -1, s = 8 * rect.sx / 2;
    ctx.save(); ctx.globalAlpha = 0.85; ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + d * s * 1.6, y - s); ctx.lineTo(x + d * s * 1.6, y + s); ctx.fill();
    ctx.font = `bold ${Math.max(10, 6 * rect.sx)}px ui-monospace,Consolas,monospace`; ctx.textAlign = left ? "left" : "right";
    ctx.fillText(`${label} ${Math.round(g.distance / 16)}▸`.replace("▸", left ? "◂" : "▸"), x + d * s * 2.2, y + s / 2);
    ctx.restore();
  }
  function hud(ctx, rect, live, ghosts, fps) {
    const lines = [[`RUN ${fmtTime(live.run_frame, fps)}  ${live.attempt_level || live.level} ${fmtTime(live.level_frame, fps)}`, "#fff"]];
    const lead = ghosts[0];
    if (lead) {
      lines.push([`vs ${lead.label}`, lead.color]);
      for (const r of raceRows(live, lead.run, fps).slice(-4))
        lines.push([r.text, r.delta == null ? "#ddd" : r.delta > 0 ? "#ff8a80" : "#b9f6ca"]);
      if (lead.finished != null) lines.push([`${lead.label} finished in ${fmtTime(lead.finished, fps)}`, lead.color]);
    }
    for (const g of ghosts) if (g.where) lines.push([`${g.label}: ${g.where}`, g.color]);
    const fs = Math.max(11, Math.min(16, 5.5 * rect.sx));
    ctx.save(); ctx.font = `${fs}px ui-monospace,Consolas,monospace`;
    const w = Math.max(...lines.map(l => ctx.measureText(l[0]).width)) + 14, h = lines.length * (fs + 3) + 8;
    const x = rect.x + 8, y = rect.y + rect.h - h - 8;
    ctx.globalAlpha = 0.72; ctx.fillStyle = "#000"; ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1;
    lines.forEach(([t, c], i) => { ctx.fillStyle = c; ctx.fillText(t, x + 7, y + 4 + (i + 1) * (fs + 3) - 3); });
    ctx.restore();
  }

  // ------------------------------------------------------------------------------------------------ the panel
  const S = { sid: null, gid: null, data: null, tracks: new Map(), live: null, liveAt: 0, vscr: 0, poll: null, raf: 0,
    canvas: null, aspect: null, autoVotes: [], api: null, tok: "", busy: false, lastRun: null, confirm: null, open: {} };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const doc = () => env.document;

  async function fetchLive() {
    if (!S.sid) return;
    try {
      const r = await env.fetch(`/api/ghosts/live/${encodeURIComponent(S.sid)}`, { headers: { authorization: "Bearer " + S.tok } });
      const L = await r.json(), now = env.performance.now();
      if (S.live?.on && L.on && L.run_frame != null && S.live.run_frame != null && L.run_frame > S.live.run_frame && L.level === S.live.level)
        S.vscr = Math.max(0, (L.scr - S.live.scr) / (L.run_frame - S.live.run_frame));
      if (S.live?.run_id && S.live.run_id !== L.run_id) env.setTimeout(load, 1500);   // a run ended: list it
      S.live = L; S.liveAt = now; statusLine();
    } catch { /* the next poll tries again */ }
  }
  function extrapolated() {
    const L = S.live; if (!L?.on) return null;
    if (!L.in_play || L.run_frame == null) return L;
    const df = Math.min(15, (env.performance.now() - S.liveAt) / 1000 * (L.fps || 60.0988));
    return { ...L, run_frame: L.run_frame + df, level_frame: L.level_frame == null ? null : L.level_frame + df, scr: L.scr + S.vscr * df };
  }
  function pictureEl() {
    const v = doc().querySelector("#nativeslot video.gbox-gpu-video");
    if (v?.videoWidth && v.style.display !== "none") return { el: v, w: v.videoWidth, h: v.videoHeight };
    const img = doc().getElementById("scr");
    if (img?.naturalWidth) return { el: img, w: img.naturalWidth, h: img.naturalHeight };
    return null;
  }
  function currentRect(pic) {
    const b = pic.el.getBoundingClientRect(), prefs = S.data?.prefs || {}, pr = prefs.picture || {};
    const aspect = pr.aspect === "auto" ? (S.aspect || "4:3") : pr.aspect;
    return pictureRect({ x: b.left, y: b.top, w: b.width, h: b.height }, pic, { ...pr, aspect }, S.data?.profile?.screen);
  }
  function autoAspect(pic) {                         // Auto picture: score each candidate on the current frame
    const L = S.live, pr = S.data?.prefs?.picture || {};
    if (pr.aspect !== "auto" || !L?.in_play || L.y == null || Math.floor(L.y / 256) !== 1 || S.autoVotes.length >= 5) return;
    try {
      const c = doc().createElement("canvas"); c.width = pic.w; c.height = pic.h;
      const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(pic.el, 0, 0);
      const img = g.getImageData(0, 0, c.width, c.height).data;
      const px = (x, y) => { x = Math.max(0, Math.min(c.width - 1, x)); y = Math.max(0, Math.min(c.height - 1, y)); const o = (y * c.width + x) * 4; return [img[o], img[o + 1], img[o + 2]]; };
      const scores = AUTO_CANDIDATES.map(a => [a, aspectScore(px, pictureRect({ x: 0, y: 0, w: pic.w, h: pic.h }, pic, { ...pr, aspect: a }, S.data?.profile?.screen), L, S.data?.profile)]);
      scores.sort((p, q) => q[1] - p[1]);
      if (scores[0][1] > 0.25 && scores[0][1] - scores[1][1] > 0.1) S.autoVotes.push(scores[0][0]);
      const tally = {}; S.autoVotes.forEach(v => tally[v] = (tally[v] || 0) + 1);
      S.aspect = Object.entries(tally).sort((p, q) => q[1] - p[1])[0]?.[0] || S.aspect;
    } catch { S.autoVotes.push(S.aspect || "4:3"); }   // a tainted / undecodable frame: keep the default
  }
  function draw() {
    S.raf = 0;
    if (!S.sid || !doc().getElementById("ghost-runs")) return unmountOverlay();
    S.raf = env.requestAnimationFrame(draw);
    const pic = pictureEl(), cv = S.canvas, prefs = S.data?.prefs || {};
    const ctx = cv?.getContext("2d");
    if (!ctx) return;
    if (!pic) { cv.style.display = "none"; return; }
    const rect0 = currentRect(pic), dpr = env.devicePixelRatio || 1;
    Object.assign(cv.style, { display: "block", left: rect0.x + "px", top: rect0.y + "px", width: rect0.w + "px", height: rect0.h + "px" });
    if (cv.width !== Math.round(rect0.w * dpr) || cv.height !== Math.round(rect0.h * dpr)) { cv.width = Math.round(rect0.w * dpr); cv.height = Math.round(rect0.h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, rect0.w, rect0.h);
    const rect = { ...rect0, x: 0, y: 0, map: (nx, ny) => { const [a, b] = rect0.map(nx, ny); return [a - rect0.x, b - rect0.y]; } };
    const live = extrapolated(); if (!live?.on || live.oper !== 1) return;
    const fps = live.fps || 60.0988, ghosts = [];
    for (const rid of S.data?.showing || []) {
      const run = S.tracks.get(rid); if (!run?.track) continue;
      const meta = S.data.runs.find(r => r.run_id === rid) || run;
      const color = prefs.colors?.[rid] || meta.color || "#4fc3f7", label = `#${meta.number || "?"}${meta.name ? " " + meta.name : ""}`;
      const gf = ghostFrame(run, live, prefs.mode || "level"), row = sampleAt(run.track, gf);
      const att = attemptOf(run, live, prefs.mode || "level");
      const g = { run, label, color, finished: att && gf != null && gf > att.end ? att.end - att.start : null, where: "" };
      ghosts.push(g);
      if (!row) { g.where = gf == null ? "" : "not on this level"; continue; }
      const scr = ghostScreen(row, live, S.data.profile);
      if (!scr) { g.where = levelName(row.lv) !== live.level ? `on ${levelName(row.lv)}` : "in another room"; continue; }
      if (!scr.visible) continue;
      const alpha = g.finished != null ? 0.18 : 0.5;
      if (scr.side) edgeArrow(ctx, scr, rect, color, label.split(" ")[0]);
      else figure(ctx, scr, rect, color, alpha, label.split(" ")[0]);
    }
    if (prefs.me && live.in_play) {                  // your own box, to check the picture alignment
      const [x, y] = rect.map(live.relx, live.rely + 1 + (live.small ? 16 : 0));
      ctx.save(); ctx.strokeStyle = "#fff"; ctx.setLineDash([3, 3]); ctx.lineWidth = 1.5;
      ctx.strokeRect(x, y, 16 * rect.sx, (live.small ? 16 : 32) * rect.sy); ctx.restore();
    }
    if (prefs.hud !== false && live.run_frame != null) hud(ctx, rect, live, ghosts, fps);
  }
  function mountOverlay() {
    if (S.canvas?.isConnected) return;
    const c = S.canvas = doc().createElement("canvas"); c.id = "ghost-canvas"; c.setAttribute("aria-hidden", "true");
    Object.assign(c.style, { position: "fixed", pointerEvents: "none", zIndex: "30", display: "none" });
    doc().body.append(c);
    if (!S.raf) S.raf = env.requestAnimationFrame(draw);
    if (!S.poll) S.poll = env.setInterval(fetchLive, 66);
    if (!S.autoTimer) S.autoTimer = env.setInterval(() => { const p = pictureEl(); if (p) autoAspect(p); }, 1500);
  }
  function unmountOverlay() {
    if (S.raf) env.cancelAnimationFrame(S.raf); S.raf = 0;
    if (S.poll) env.clearInterval(S.poll); S.poll = null;
    if (S.autoTimer) env.clearInterval(S.autoTimer); S.autoTimer = null;
    if (S.tasTimer) env.clearInterval(S.tasTimer); S.tasTimer = null;
    S.canvas?.remove(); S.canvas = null;
  }

  async function load() {
    if (!S.gid) return;
    S.data = await S.api(`/api/ghosts/game/${encodeURIComponent(S.gid)}`);
    try { S.tas = await S.api(`/api/tas/runs?game_id=${encodeURIComponent(S.gid)}&session_id=${encodeURIComponent(S.sid)}`); }
    catch (error) { S.tas = { runs: [], error: String(error) }; }
    for (const rid of S.data.showing || []) if (!S.tracks.has(rid)) {
      try { S.tracks.set(rid, await S.api(`/api/ghosts/runs/${encodeURIComponent(rid)}`)); } catch { /* deleted meanwhile */ }
    }
    render();
  }
  async function refreshNative() {
    const sid = S.sid, gid = S.gid;
    if (!doc().getElementById('ghost-runs')) return;
    try {
      const data = await S.api(`/api/tas/runs?game_id=${encodeURIComponent(gid)}&session_id=${encodeURIComponent(sid)}`);
      if (sid !== S.sid || gid !== S.gid) return;
      const changed = (data.runs || []).map(r => r.id).join() !== (S.tas?.runs || []).map(r => r.id).join();
      S.tas = data;
      if (changed) return render();
      const status = doc().getElementById('tas-capture-status');
      if (status && data.capture) status.textContent = `Capture: ${data.capture.state}${data.capture.frame != null ? ' · '+Number(data.capture.frame).toLocaleString()+' frames' : ''}${data.capture.reason ? ' · '+data.capture.reason : ''}`;
    } catch { /* refresh button and the next heartbeat retry */ }
  }
  async function setPrefs(p) {
    S.data.prefs = await S.api(`/api/ghosts/game/${encodeURIComponent(S.gid)}/prefs`, p);
    if (p.picture) { S.aspect = null; S.autoVotes = []; }
    await load();
  }
  function statusLine() {
    const el = doc().getElementById("gr-status"); if (!el) return;
    const L = S.live, fps = L?.fps || 60.0988;
    el.innerHTML = !L?.on ? `<span class="mut">Recorder idle: runs are recorded while you play</span>`
      : L.run_id ? `<span class="ok">● Recording</span> ${esc(L.attempt_level || L.level)} · run ${fmtTime(L.run_frame, fps)}${L.deaths ? ` · ${L.deaths} death${L.deaths > 1 ? "s" : ""}` : ""}${L.assisted ? ` · <span class="mut" title="Rewind or a loaded state: kept, never best">assisted</span>` : ""}`
      : `<span class="mut">Waiting for a run: press Start on the title screen</span>`;
  }
  function render() {
    const host = doc().getElementById("ghost-runs"); if (!host || !S.data) return;
    const d = S.data, p = d.prefs, fps = d.profile?.fps || 60.0988;
    if (!d.profile) { host.innerHTML = `<p class="mut">Ghost runs need a game profile (RAM layout). Supported: Super Mario Bros. (NES).</p>`; return; }
    const shown = new Set(d.showing), pic = pictureEl(), docked = !pic && doc().getElementById("nativeslot");
    const pick = (k, t, title) => `<button class="act${p.pick === k ? " pri" : ""}" data-pick="${k}" title="${esc(title)}">${t}</button>`;
    const rows = d.runs.map(r => {
      const sp = (r.splits || []).map(s => `<tr><td>${esc(s.level)}</td><td title="From the first try at this level to clearing it">${fmtTime(s.frames, fps)}</td>
        <td class="mut" title="The clearing try alone">seg ${fmtTime(s.segment, fps)}${d.level_bests[s.level]?.run_id === r.run_id ? ' <span class="ok" title="Best segment of this level">★</span>' : ""}</td>
        <td class="mut">${s.deaths ? `${s.deaths} death${s.deaths > 1 ? "s" : ""}` : ""}</td></tr>`).join("");
      const when = r.started_at ? new Date(r.started_at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
      const del = S.confirm === r.run_id;
      return `<div class="gr-run${shown.has(r.run_id) ? " on" : ""}" data-rid="${esc(r.run_id)}">
        <div class="gr-row"><input type="checkbox" class="gr-show" ${shown.has(r.run_id) ? "checked" : ""} title="Show this ghost" aria-label="Show ghost #${r.number}">
          <input type="color" class="gr-color" value="${esc(p.colors?.[r.run_id] || r.color)}" title="Ghost colour" aria-label="Ghost colour">
          <b class="gr-name" title="Double-click to rename">#${r.number}${r.name ? " " + esc(r.name) : ""}</b>
          ${r.best ? '<span class="gr-badge" title="Fastest complete run">★ best</span>' : r.best_progress ? '<span class="gr-badge" title="No complete run yet: furthest, fastest">★ furthest</span>' : ""}
          <span class="gr-time">${fmtTime(r.frames, fps)}</span></div>
        <div class="gr-sub mut">${esc(r.start_level)} → ${esc(r.end_level)} · ${esc(r.outcome.replace("_", " "))}${r.deaths ? ` · ${r.deaths} death${r.deaths > 1 ? "s" : ""}` : ""}${r.assisted ? " · assisted" : ""} · ${esc(when)}
          <span class="gr-acts"><button class="act gr-ren" title="Rename">✎</button><button class="act gr-del${del ? " bad" : ""}" title="Delete this run">${del ? "Delete?" : "🗑"}</button></span></div>
        ${sp ? `<details class="gr-splits" ${S.open[r.run_id] ? "open" : ""}><summary class="mut">${r.splits.length} split${r.splits.length > 1 ? "s" : ""}</summary><table>${sp}</table></details>` : ""}</div>`;
    }).join("");
    host.innerHTML = `${tasHtml(S.tas)}<p id="gr-status" class="gr-status"></p>
      ${docked ? `<p class="bad" style="font-size:11.5px">This game is docked as a native window, which nothing can draw over. Turn on the GPU compositor (top bar) to see the ghosts; runs are still recorded.</p>` : ""}
      <div class="gr-bar"><span class="mut">Ghosts</span>${pick("best", "Best", "Your best run (fastest complete, else furthest)")}${pick("last", "Last " + (p.last_n || 3), "Your last runs, stacked")}${pick("pb_segments", "Best levels", "For each level, the run with its fastest segment")}${pick("custom", "Picked", "The runs ticked below")}${pick("none", "Off", "No ghosts")}</div>
      <div class="gr-bar"><span class="mut">Sync</span><button class="act${p.mode !== "run" ? " pri" : ""}" data-mode="level" title="Race each level from its start (you vs the ghost on the same level)">Level</button><button class="act${p.mode === "run" ? " pri" : ""}" data-mode="run" title="Race the whole run from the first frame">Run</button>
        <label title="Race timer and splits over the game"><input type="checkbox" id="gr-hud" ${p.hud !== false ? "checked" : ""}> Timer</label>
        <label title="Outline yourself, to check the ghosts line up with the picture"><input type="checkbox" id="gr-me" ${p.me ? "checked" : ""}> Me</label>
        <select id="gr-aspect" title="How the emulator shows the picture (Auto: measured on your player)" aria-label="Picture aspect">${["auto", "4:3", "8:7", "1:1", "fill"].map(a => `<option value="${a}" ${(p.picture?.aspect || "4:3") === a ? "selected" : ""}>${{ auto: `Auto${S.aspect ? " (" + S.aspect + ")" : ""}`, "4:3": "4:3", "8:7": "8:7 pixels", "1:1": "Square pixels", fill: "Fill" }[a]}</option>`).join("")}</select></div>
      <div class="gr-list">${rows || `<p class="mut">No runs yet. Play: every run is recorded, from Start to game over or the end.</p>`}</div>`;
    statusLine();
  }
  function tasHtml(data) {
    const rows = (data?.runs || []).map(r => `<article class="gr-run tas-run" data-tas="${esc(r.id)}">
      <b>${esc(r.title || 'Mario run')}</b> <span class="mut">${Number(r.frames).toLocaleString()} frames · ${Number(r.state_restores)} state restores</span>
      <p class="mut">${r.full_verified_sprites?.length ? 'Full replay verified: '+r.full_verified_sprites.map(x => esc(x || 'Original Mario')).join(', ') : 'Recorded; full playback verification pending'}</p>
      <div class="gr-bar"><select class="tas-segment" aria-label="Replay segment"><option value="">Entire run</option>${(r.segments || []).map((s, i) => `<option value="${esc(s.id)}">${esc(s.label)} · attempt ${i+1}</option>`).join('')}</select>
      <label><input class="tas-loop" type="checkbox"> Loop</label><button class="act pri tas-play">▶ Play</button></div>
      <label>Player sprite <select class="tas-sprite" aria-label="Replay sprite">${[['', 'Original Mario'], ['sonic', 'Sonic'], ['mario2', 'Mario 2'], ['mario3', 'Mario 3'], ['smw', 'Super Mario World Mario']].map(([id, label]) => `<option value="${id}" ${r.idle?.sprite === id ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
      <p><label><input class="tas-idle" type="checkbox" ${r.idle?.enabled ? 'checked' : ''}> Use as idle screensaver on available PCs</label></p>
      <p class="mut tas-result" role="status">${r.idle?.enabled ? 'Armed; waits for a verified full run and an idle PC.' : 'Playback uses a separate test session and yields when you return.'}</p>
      </article>`).join('');
    return `<section class="tas-runs"><b>Native TAS playback</b><button class="act tas-refresh" style="float:right">Refresh runs</button>
      <p id="tas-capture-status" class="${data?.capture?.state === 'recording' ? 'ok' : 'mut'}">${data?.capture ? `Capture: ${esc(data.capture.state)}${data.capture.frame != null ? ' · '+Number(data.capture.frame).toLocaleString()+' frames' : ''}${data.capture.reason ? ' · '+esc(data.capture.reason) : ''}` : ''}</p>
      ${data?.error ? `<p class="bad">Native archive unavailable: ${esc(data.error)}</p>` : ''}
      ${rows || '<p class="mut">New SMB1 sessions capture native inputs, checkpoints and rewind branches. The tape becomes available here after the emulator closes.</p>'}
      <p class="mut">${esc(data?.legacy_reason || 'Earlier ghost tracks do not contain the native input tape required for exact replay.')}</p></section>`;
  }
  async function playTas(button) {
    const row = button.closest('.tas-run'), message = row.querySelector('.tas-result');
    button.disabled = true; message.textContent = 'Finding an available idle PC…';
    try {
      let job = await S.api(`/api/tas/runs/${encodeURIComponent(row.dataset.tas)}/play`, {
        segment: row.querySelector('.tas-segment').value, loop: row.querySelector('.tas-loop').checked,
        sprite: row.querySelector('.tas-sprite').value.trim()
      });
      if (['failed', 'rejected'].includes(job.state)) throw Error(job.error || 'Replay could not start');
      message.textContent = `Replay queued (${job.id || job.job_id}); it will not close your current game.`;
      for (let i = 0; i < 900 && row.isConnected && ['queued', 'running'].includes(job.state); i++) {
        await new Promise(resolve => env.setTimeout(resolve, 1000));
        job = await S.api('/api/jobs/' + encodeURIComponent(job.id));
        message.textContent = job.progress?.msg || `Replay ${job.state}`;
      }
      if (['failed', 'rejected'].includes(job.state)) throw Error(job.error || 'Replay failed');
      if (job.output?.session_id) message.textContent = `Playing in test session ${job.output.session_id}. Use Sessions to watch it.`;
    } catch (error) { message.textContent = String(error); }
    finally { button.disabled = false; }
  }
  function onClick(e) {
    const t = e.target, host = doc().getElementById("ghost-runs"); if (!host?.contains(t)) return;
    if (t.classList.contains('tas-play')) return playTas(t);
    if (t.classList.contains('tas-refresh')) return load();
    const rid = t.closest(".gr-run")?.dataset.rid;
    if (t.dataset.pick) return setPrefs({ pick: t.dataset.pick, ...(t.dataset.pick === "last" && S.data.prefs.pick === "last" ? { last_n: (S.data.prefs.last_n % 5) + 1 } : {}) });
    if (t.dataset.mode) return setPrefs({ mode: t.dataset.mode });
    if (t.classList.contains("gr-show")) {
      const set = new Set(S.data.showing);
      t.checked ? set.add(rid) : set.delete(rid);
      return setPrefs({ pick: "custom", shown: [...set] });
    }
    if (t.classList.contains("gr-ren")) return rename(rid);
    if (t.classList.contains("gr-del")) {
      if (S.confirm !== rid) { S.confirm = rid; render(); env.setTimeout(() => { if (S.confirm === rid) { S.confirm = null; render(); } }, 4000); return; }
      S.confirm = null; S.tracks.delete(rid);
      return S.api(`/api/ghosts/runs/${encodeURIComponent(rid)}`, null, "DELETE").then(load);
    }
  }
  async function rename(rid) {
    const b = doc().querySelector(`.gr-run[data-rid="${rid}"] .gr-name`); if (!b) return;
    const r = S.data.runs.find(x => x.run_id === rid);
    const inp = doc().createElement("input"); inp.value = r?.name || ""; inp.placeholder = `run #${r?.number}`; inp.className = "gr-rename"; inp.maxLength = 80;
    b.replaceWith(inp); inp.focus();
    let done = false;
    const save = async ok => { if (done) return; done = true; if (ok) await S.api(`/api/ghosts/runs/${encodeURIComponent(rid)}`, { name: inp.value }, "PATCH"); await load(); };
    inp.onkeydown = e => { if (e.key === "Enter") save(true); if (e.key === "Escape") save(false); e.stopPropagation(); };
    inp.onblur = () => save(true);
  }
  function onChange(e) {
    const t = e.target, host = doc().getElementById("ghost-runs"); if (!host?.contains(t)) return;
    if (t.classList.contains('tas-idle') || t.classList.contains('tas-sprite') && t.closest('.tas-run').querySelector('.tas-idle').checked) {
      const row = t.closest('.tas-run'), message = row.querySelector('.tas-result');
      const toggle = row.querySelector('.tas-idle');
      return S.api(`/api/tas/runs/${encodeURIComponent(row.dataset.tas)}/idle`, {
        enabled: toggle.checked, sprite: row.querySelector('.tas-sprite').value.trim()
      }).then(r => { message.textContent = r.reason; }).catch(error => { toggle.checked = false; message.textContent = String(error); });
    }
    if (t.classList.contains("gr-color")) return setPrefs({ colors: { [t.closest(".gr-run").dataset.rid]: t.value } });
    if (t.id === "gr-hud") return setPrefs({ hud: t.checked });
    if (t.id === "gr-me") return setPrefs({ me: t.checked });
    if (t.id === "gr-aspect") return setPrefs({ picture: { ...(S.data.prefs.picture || {}), aspect: t.value } });
  }
  function css() {
    if (doc().getElementById("gr-css")) return;
    doc().head.insertAdjacentHTML("beforeend", `<style id="gr-css">
      #ghost-runs { font-size:12px } #ghost-runs .gr-status { margin:0 0 6px } #ghost-runs .gr-bar { display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-bottom:6px }
      #ghost-runs .gr-bar .act { padding:2px 8px; font-size:11.5px } #ghost-runs .gr-bar label { display:flex; gap:3px; align-items:center; font-size:11.5px }
      #ghost-runs .gr-bar select { font-size:11.5px; padding:1px 4px; max-width:120px } #ghost-runs .gr-list { display:flex; flex-direction:column; gap:4px; max-height:340px; overflow:auto }
      #ghost-runs .gr-run { border:1px solid var(--line); border-radius:6px; padding:4px 6px } #ghost-runs .gr-run.on { border-color:var(--acc) }
      #ghost-runs .gr-row { display:flex; gap:6px; align-items:center } #ghost-runs .gr-color { width:20px; height:18px; padding:0; border:0; background:none; cursor:pointer }
      #ghost-runs .gr-name { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:text } #ghost-runs .gr-time { font:12px ui-monospace,Consolas,monospace }
      #ghost-runs .gr-badge { font-size:10.5px; padding:0 6px; border-radius:8px; background:color-mix(in srgb, var(--acc) 25%, transparent) }
      #ghost-runs .gr-sub { display:flex; flex-wrap:wrap; gap:4px; align-items:center; font-size:11px; margin-top:2px } #ghost-runs .gr-acts { margin-left:auto; display:flex; gap:3px }
      #ghost-runs .gr-acts .act { padding:0 6px; font-size:11px } #ghost-runs .gr-splits table { width:100%; font:11px ui-monospace,Consolas,monospace; border-collapse:collapse }
      #ghost-runs .gr-splits td { padding:1px 4px } #ghost-runs .gr-rename { flex:1; min-width:0; font-size:12px }</style>`);
  }
  async function mount({ sid, gid, api, tok, into }) {
    if (!sid || !gid) return false;
    S.sid = sid; S.gid = gid; S.api = api; S.tok = tok || ""; S.live = null; S.confirm = null;
    css();
    let host = doc().getElementById("ghost-runs");
    if (!host) {
      const target = into || doc().getElementById("dock-top") || doc().getElementById("dock-side"); if (!target) return false;
      target.insertAdjacentHTML("beforeend", `<details open data-dock="runs" class="sect"><summary draggable="true">Runs <span class="mut">TAS playback and ghosts</span></summary><div id="ghost-runs"><p class="mut">loading…</p></div></details>`);
      host = doc().getElementById("ghost-runs");
      host.addEventListener("click", onClick); host.addEventListener("change", onChange);
      host.addEventListener("toggle", e => { const rid = e.target.closest?.(".gr-run")?.dataset.rid; if (rid && e.target.matches("details")) S.open[rid] = e.target.open; }, true);
    }
    await load();
    if (!S.data?.profile) { host.closest("details")?.remove(); return false; }
    mountOverlay(); fetchLive();
    if (!S.tasTimer) S.tasTimer = env.setInterval(refreshNative, 10000);
    return true;
  }
  return { mount, unmount: unmountOverlay, ghostFrame, attemptOf, sampleAt, ghostScreen, pictureRect, fmtTime, fmtDelta, raceRows,
    aspectScore, levelName, ASPECTS, tasHtml, _state: S };
});
