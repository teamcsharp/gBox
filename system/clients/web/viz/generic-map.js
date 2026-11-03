// Generic top-down live map for any hooked title that has no bespoke renderer yet (the GBoxLiveMaps
// fallback). It polls the title-agnostic autoplay telemetry and plots whatever world positions it can
// find (the steering-evidence player poses most bots emit, or a positions array), auto-fitting the
// view, with a short motion trail per entity so a frozen entity is obvious - the same "are they
// moving?" read as the PSO map. When a title exposes no positions it still shows the live session
// status (title / running / screen / floor), so a pane is never blank. Read-only; no interaction.
// GBoxGenericMap.html(sid) / mount(doc,{sid,api}) / detach() - same shape as the other providers.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const num = v => typeof v === "number" && isFinite(v);
  const COLORS = ["#5a8ae0", "#e0894a", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7"];

  // Any [{slot,x,z,hp}] world positions the title's telemetry exposes (pure).
  function positions(tel) {
    const st = (tel && tel.stats) || {}, out = [];
    const push = (slot, x, z, hp) => { if (num(x) && num(z)) out.push({ slot, x, z, hp: num(hp) ? hp : null }); };
    try {
      const d = JSON.parse(st.steering_evidence_json || "null");
      const ev = d && Array.isArray(d.events) && d.events[d.events.length - 1];
      const ps = (ev && ev.players) || {};
      for (const k of Object.keys(ps)) { const p = ps[k].after || ps[k].before || {}; push(parseInt(k, 10) || k, p.x, p.z, p.hp); }
    } catch (e) { /* no steering evidence */ }
    if (!out.length && Array.isArray(st.positions))
      st.positions.forEach((p, i) => Array.isArray(p) ? push(i + 1, p[0], p[1]) : p && push(i + 1, p.x, p.z, p.hp));
    return out;
  }

  // World->pixel auto-fit over the points (pure).
  function fit(pts, w, h) {
    if (!pts.length) return null;
    let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
    for (const p of pts) { a = Math.min(a, p.x); c = Math.max(c, p.x); b = Math.min(b, p.z); d = Math.max(d, p.z); }
    const pad = Math.max(120, (c - a) * 0.3, (d - b) * 0.3);
    a -= pad; b -= pad; c += pad; d += pad;
    const s = Math.min(w / Math.max(1, c - a), h / Math.max(1, d - b)) * 0.92;
    return { a, b, s, ox: (w - (c - a) * s) / 2, oy: (h - (d - b) * s) / 2 };
  }
  const project = (f, x, z) => [f.ox + (x - f.a) * f.s, f.oy + (z - f.b) * f.s];

  const CSS = `.genmap{display:flex;flex-direction:column;gap:6px;font-size:12px}
    .genmap .gm-hud{display:flex;flex-wrap:wrap;gap:4px 10px}
    .genmap .gm-where{font-weight:600}
    .genmap .gm-mut{color:#9eafc4}
    .genmap .gm-stage{position:relative;border:1px solid #344155;border-radius:8px;overflow:hidden;background:#121821}
    .genmap canvas{display:block;width:100%}
    .genmap .gm-status{position:absolute;left:8px;right:8px;top:8px;text-align:center;color:#fff;font-weight:600;text-shadow:0 0 3px #000,0 0 3px #000;pointer-events:none}
    .genmap .gm-status:empty{display:none}`;
  function style(doc) { if (doc.head && !doc.getElementById("gen-map-css")) { const s = doc.createElement("style"); s.id = "gen-map-css"; s.textContent = CSS; doc.head.append(s); } }

  function html(sid) {
    return `<div class="genmap" data-genmap="${ESC(sid)}">` +
      `<div class="gm-hud"><span class="gm-where" data-gm="where">Live map</span><span class="gm-mut" data-gm="count"></span></div>` +
      `<div class="gm-stage"><canvas role="img" aria-label="Top-down live position map"></canvas><div class="gm-status" data-gm="status"></div></div>` +
      `<div class="gm-mut">Generic top-down view (positions + motion). No bespoke map for this title yet.</div></div>`;
  }

  let current = null;
  function mount(doc, { sid, api }) {
    detach(); style(doc);
    const wrap = doc.querySelector(`.genmap[data-genmap="${CSS_ESC(sid)}"]`) || doc.querySelector(".genmap");
    if (!wrap || !api) return null;
    const canvas = wrap.querySelector("canvas"), $ = k => wrap.querySelector(`[data-gm="${k}"]`);
    let stopped = false, timer = null, size = { w: 0, h: 0 };
    const trails = new Map();
    const nowMs = () => (root.performance && root.performance.now ? root.performance.now() : Date.now());

    function fitCanvas() {
      const w = Math.round(wrap.clientWidth) || 320, h = Math.round(Math.max(240, Math.min(w * 0.8, 520)));
      const dpr = Math.min(root.devicePixelRatio || 1, 3);
      if (w === size.w && h === size.h) return;
      size = { w, h }; canvas.style.height = h + "px"; canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    function pushTrail(pts) {
      const t0 = nowMs();
      for (const p of pts) { let tr = trails.get(p.slot); if (!tr) trails.set(p.slot, tr = []);
        const last = tr[tr.length - 1];
        if (!last || Math.hypot(p.x - last.x, p.z - last.z) >= 0.75) tr.push({ x: p.x, z: p.z });
        while (tr.length > 48) tr.shift(); }
      const live = new Set(pts.map(p => p.slot));
      for (const k of [...trails.keys()]) if (!live.has(k)) trails.delete(k);
    }
    function render(tel) {
      if (stopped) return;
      fitCanvas();
      const ctx = canvas.getContext && canvas.getContext("2d"); if (!ctx) return;
      const dpr = canvas.width / Math.max(size.w, 1); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#121821"; ctx.fillRect(0, 0, size.w, size.h);
      const st = (tel && tel.stats) || {}, pts = positions(tel);
      if (pts.length) pushTrail(pts);
      const f = fit(pts, size.w, size.h);
      if (f) {
        trails.forEach((tr, slot) => { if (tr.length < 2) return;
          ctx.strokeStyle = COLORS[(Number(slot) - 1 + COLORS.length) % COLORS.length] || "#5a8ae0";
          ctx.lineWidth = slot === 1 ? 3 : 2; ctx.lineCap = "round";
          for (let i = 1; i < tr.length; i++) { const x = project(f, tr[i - 1].x, tr[i - 1].z), y = project(f, tr[i].x, tr[i].z);
            ctx.globalAlpha = 0.12 + 0.6 * (i / tr.length); ctx.beginPath(); ctx.moveTo(x[0], x[1]); ctx.lineTo(y[0], y[1]); ctx.stroke(); }
          ctx.globalAlpha = 1; });
        for (const p of pts) { const [x, y] = project(f, p.x, p.z);
          ctx.beginPath(); ctx.arc(x, y, p.slot === 1 ? 7 : 5, 0, 2 * Math.PI);
          ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; ctx.stroke();
          ctx.fillStyle = COLORS[(Number(p.slot) - 1 + COLORS.length) % COLORS.length] || "#5a8ae0"; ctx.fill(); }
      }
      $("where").textContent = (tel && tel.title) || "Live map";
      const bits = [];
      if (tel) bits.push(tel.running ? "running" : "idle");
      if (num(st.floor)) bits.push("floor " + st.floor);
      if (st.screen) bits.push(String(st.screen));
      bits.push(pts.length + " tracked");
      $("count").textContent = bits.join(" · ");
      $("status").textContent = tel ? (pts.length ? "" : "No position data exposed for this title yet — showing live status") : "Waiting for telemetry…";
    }
    async function tick() {
      timer = null; if (stopped) return;
      let tel = null; try { tel = await api(`/api/autoplay/telemetry/${encodeURIComponent(sid)}`); } catch (e) { tel = null; }
      if (stopped) return; render(tel);
      timer = root.setTimeout(tick, 900);
    }
    const ro = root.ResizeObserver ? new root.ResizeObserver(() => render(last)) : null; let last = null;
    const origRender = render; render = tel => { last = tel || last; origRender(tel); };
    ro && ro.observe(wrap.querySelector(".gm-stage"));
    tick();
    function stop() { stopped = true; if (timer) root.clearTimeout(timer); ro && ro.disconnect(); if (current === ctl) current = null; }
    const ctl = { stop, get sid() { return sid; } };
    current = ctl; return ctl;
  }
  function detach() { if (current) current.stop(); current = null; }
  function CSS_ESC(s) { return String(s).replace(/["\\\]]/g, "\\$&"); }

  const api = { html, mount, detach, positions, fit, project };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxGenericMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
