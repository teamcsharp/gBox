// PSO interactive 2D map (operator 2026-11-02: "the bot shouldnt even need to see. the 2d map is the
// real goal - once we look at that we can point people on a 2d level where they want to go ... a
// pathfinding system where they find their way to wherever I click - double-click an area and they
// navigate to it like an RTS. If idle they continue to the portal/teleporter to leave the level"):
// a top-down map of the PSO level built ENTIRELY from the game's RAM (no vision), drawn by gBox from
// the nav agent's extracted walkable surface + live entities + the knowledge crystal. It polls
//   GET /api/pso/map/{sid}                 the RAM-derived map model (~1.5 a second while open)
// and draws: the walkable surface as the floor (navigable space; walls = the void around it), the
// switches (clickable, pressed/unpressed), the doors/barriers (red locked / green open), the area
// warps and the exit teleporter, the enemies (dots by class, hollow when dead), and the players
// (P1 the leader as a filled arrow, P2-4 the swarm). P1's A* path and current target draw on top.
// Click to command (docs/pso-map-directives.md):
//   double-click an open point -> GOTO {x,z}   (RTS move order; P1 pathfinds there)
//   click a switch -> PRESS      click an enemy -> ATTACK      click a door -> OPEN (go to it)
//   Resume autonomous -> CLEAR   (P1 goes back to heading for the exit teleporter when idle)
// issued via POST /api/sessions/{sid}/pso-directive. Zoom with the wheel, pan by dragging; it fits
// the area on first frame. Hidden until a PSO session's first frame comes.
//   GBoxPsoMap.html(sid) / mount(doc,{sid,api}) / detach() / create({sid,api,...}) + pure helpers.
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const KEY = "gbox_pso_map";
  const FAST_MS = 650, SLOW_MS = 3000;
  const VIEW = { x: -1, z: 1 };                 // +z up, +x left: the right-handed world seen from above
  const CLASS_COLORS = ["#e34948", "#f28e2b", "#b07aa1", "#59a14f", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
  function classColor(cls) {
    if (!cls) return "#e34948";
    let h = 0; for (const ch of String(cls)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return CLASS_COLORS[h % CLASS_COLORS.length];
  }

  // ---- world <-> pixel (pure; same transform as the tactical map, PSO world units) ----
  function viewOf(w, size) {
    return { cx: w.cx, cz: w.cz, rot: w.rot || 0, w: size.w, h: size.h,
             scale: Math.min(size.w, size.h) / 2 / Math.max(w.radius, 1) };
  }
  function project(v, x, z) {
    const r = VIEW.x * (x - v.cx), u = VIEW.z * (z - v.cz), c = Math.cos(v.rot), s = Math.sin(v.rot);
    return [v.w / 2 + (r * c - u * s) * v.scale, v.h / 2 - (r * s + u * c) * v.scale];
  }
  function unproject(v, x, y) {
    const a = (x - v.w / 2) / v.scale, b = -(y - v.h / 2) / v.scale;
    const c = Math.cos(v.rot), s = Math.sin(v.rot);
    return [v.cx + (a * c + b * s) / VIEW.x, v.cz + (-a * s + b * c) / VIEW.z];
  }
  function panView(camera, size, dx, dy) {
    const v = viewOf(camera, size), a = unproject(v, 0, 0), b = unproject(v, dx, dy);
    return { ...camera, cx: camera.cx + a[0] - b[0], cz: camera.cz + a[1] - b[1] };
  }
  function zoomView(camera, size, x, y, factor) {
    const before = unproject(viewOf(camera, size), x, y);
    const next = { ...camera, radius: Math.max(40, Math.min(500000, camera.radius * factor)) };
    const after = unproject(viewOf(next, size), x, y);
    next.cx += before[0] - after[0]; next.cz += before[1] - after[1];
    return next;
  }
  // the camera that fits an area's bounds (or centres on the players)
  function fitCamera(model) {
    const b = model && model.bounds;
    if (Array.isArray(b) && b.length === 4 && b.every(Number.isFinite)) {
      return { cx: (b[0] + b[2]) / 2, cz: (b[1] + b[3]) / 2,
               radius: Math.max(b[2] - b[0], b[3] - b[1]) / 2 * 1.08 || 1000, rot: 0 };
    }
    const p = (model && model.players || []).find(q => q.slot === 1) || (model && model.players || [])[0];
    return { cx: p ? p.x : 0, cz: p ? p.z : 0, radius: 2000, rot: 0 };
  }

  // ---- the walkable surface (pure): a list of screen rects for the navigable cells ----
  function decodeBits(b64) {
    try {
      const bin = (root.atob ? root.atob(b64) : Buffer.from(b64, "base64").toString("binary"));
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    } catch { return null; }
  }
  // walkable world cells as [x0,z0,x1,z1] rectangles (bit grid), or null; capped so a huge grid can't stall
  function surfaceCells(surface, limit = 20000) {
    if (!surface || typeof surface !== "object") return null;
    const { origin, cell, cols, rows } = surface;
    if (surface.walk_b64 && Array.isArray(origin) && Number.isFinite(cell) && Number.isInteger(cols) && Number.isInteger(rows)) {
      const bits = decodeBits(surface.walk_b64);
      if (!bits) return null;
      const out = [];
      for (let r = 0; r < rows && out.length < limit; r++) {
        for (let cIdx = 0; cIdx < cols; cIdx++) {
          const n = r * cols + cIdx;
          if (bits[n >> 3] & (0x80 >> (n & 7))) {
            const x0 = origin[0] + cIdx * cell, z0 = origin[1] + r * cell;
            out.push([x0, z0, x0 + cell, z0 + cell]);
          }
        }
      }
      return { rects: out, cell };
    }
    if (Array.isArray(surface.cells)) {                 // fallback point cloud: a dot per sampled point
      const c = Number.isFinite(cell) ? cell : 50;
      return { rects: surface.cells.filter(p => Array.isArray(p) && p.length >= 2)
        .slice(0, limit).map(p => [p[0] - c / 2, p[1] - c / 2, p[0] + c / 2, p[1] + c / 2]), cell: c };
    }
    return null;
  }

  // ---- the marks (pure): clickable/hoverable items, each projected to the canvas ----
  const num = v => (typeof v === "number" && isFinite(v));
  function marks(model, v) {
    const out = [];
    if (!model) return out;
    for (const w of model.warps || []) if (num(w.x) && num(w.z)) {
      const [x, y] = project(v, w.x, w.z);
      out.push({ kind: "warp", id: w.id, x, y, wx: w.x, wz: w.z, tip: `Warp${w.to ? " -> " + w.to : ""}` });
    }
    const ex = model.exit;
    if (ex && num(ex.x) && num(ex.z)) {
      const [x, y] = project(v, ex.x, ex.z);
      out.push({ kind: "exit", x, y, wx: ex.x, wz: ex.z, tip: `Exit ${ex.kind || "teleporter"} (leave the level)` });
    }
    for (const d of model.doors || []) if (num(d.x) && num(d.z)) {
      const [x, y] = project(v, d.x, d.z);
      out.push({ kind: "door", id: d.id, x, y, wx: d.x, wz: d.z, open: d.open === true,
        tip: `Door${d.type ? " " + d.type : ""} · ${d.open === true ? "open" : d.open === false ? "locked" : "state unknown"}` +
             (d.to_room != null ? ` -> room ${d.to_room}` : "") });
    }
    for (const s of model.switches || []) if (num(s.x) && num(s.z)) {
      const [x, y] = project(v, s.x, s.z);
      out.push({ kind: "switch", id: s.id, x, y, wx: s.x, wz: s.z, pressed: s.pressed === true,
        tip: `Switch · ${s.pressed === true ? "pressed" : s.pressed === false ? "unpressed" : "state unknown"}` +
             (s.opens ? ` · opens ${s.opens}` : "") });
    }
    for (const e of model.enemies || []) if (num(e.x) && num(e.z)) {
      const [x, y] = project(v, e.x, e.z);
      out.push({ kind: "enemy", id: e.id, x, y, wx: e.x, wz: e.z, alive: e.alive !== false,
        color: classColor(e.cls || e.class),
        tip: `${e.class || e.cls || "Enemy"}${e.id ? " " + e.id : ""}${e.hp != null ? " · " + e.hp + " HP" : ""}` +
             (e.alive === false ? " · dead" : "") });
    }
    for (const p of model.players || []) if (num(p.x) && num(p.z)) {
      const [x, y] = project(v, p.x, p.z);
      const leader = p.slot === 1 || p.role === "leader";
      out.push({ kind: "player", slot: p.slot, x, y, leader, heading: p.heading,
        tip: `${leader ? "P1 (leader)" : "P" + (p.slot ?? "?") + " (swarm)"}${p.hp != null ? " · " + p.hp + " HP" : ""}` });
    }
    return out;
  }

  // ---- drawing ----
  const THEME_LIGHT = { void: "#dcdce3", floor: "#ffffff", ink: "#1b1b1f", halo: "#ffffff", muted: "#8a8a96",
    player: "#2a78d6", leader: "#1746c9", plan: "#1baf7a", locked: "#e34948", open: "#1baf7a",
    switchOn: "#1baf7a", switchOff: "#eda100", warp: "#8a5cf6", exit: "#13b5c8" };
  function themeOf() { return THEME_LIGHT; }       // PSO map uses fixed, high-contrast tokens (light + dark readable)

  function draw(ctx, s) {
    const { model: m, view: v, theme: t } = s;
    ctx.save();
    ctx.fillStyle = t.void; ctx.fillRect(0, 0, v.w, v.h);
    // 1. walkable surface = the navigable floor; the surrounding void reads as walls / obstacles
    const surf = surfaceCells(m && m.surface);
    if (surf) {
      ctx.fillStyle = t.floor; ctx.globalAlpha = 0.92;
      for (const [x0, z0, x1, z1] of surf.rects) {
        const a = project(v, x0, z0), b = project(v, x1, z1);
        const px = Math.min(a[0], b[0]), py = Math.min(a[1], b[1]);
        ctx.fillRect(px, py, Math.abs(b[0] - a[0]) + 0.8, Math.abs(b[1] - a[1]) + 0.8);
      }
      ctx.globalAlpha = 1;
    }
    const ms = marks(m, v);
    // 2. P1's A* path + target (the pathfinding result of a click / the route to the exit)
    const path = (m && m.path || []).filter(p => Array.isArray(p) && p.length >= 2);
    if (path.length > 1) {
      const pts = path.map(p => project(v, p[0], p[1]));
      ctx.lineWidth = 4; ctx.strokeStyle = t.halo; ctx.globalAlpha = 0.7; ctx.setLineDash([]);
      ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 2; ctx.strokeStyle = t.plan; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
    }
    const tg = m && m.target;
    if (tg && num(tg.x) && num(tg.z)) {
      const [x, y] = project(v, tg.x, tg.z);
      ctx.strokeStyle = t.plan; ctx.lineWidth = 2; ctx.beginPath();
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { ctx.moveTo(x + dx * 5, y + dy * 5); ctx.lineTo(x + dx * 12, y + dy * 12); }
      ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI); ctx.fillStyle = t.plan; ctx.fill();
    }
    // 3. marks: warps, exit, doors, switches, enemies, players (players on top)
    for (const k of ["warp", "exit", "door", "switch", "enemy", "player"]) {
      for (const mk of ms) { if (mk.kind === k) drawMark(ctx, mk, t); }
    }
    scaleBar(ctx, v, t, surf && surf.cell);
    ctx.restore();
    return ms;
  }
  function halo(ctx, fn, t) { ctx.lineWidth = 3; ctx.strokeStyle = t.halo; fn(); }
  function drawMark(ctx, m, t) {
    if (m.kind === "warp" || m.kind === "exit") {
      const col = m.kind === "exit" ? t.exit : t.warp, s = m.kind === "exit" ? 9 : 7;
      ctx.beginPath(); for (let i = 0; i < 4; i++) { const a = Math.PI / 2 * i; const fx = m.x + Math.cos(a) * s, fy = m.y + Math.sin(a) * s; i ? ctx.lineTo(fx, fy) : ctx.moveTo(fx, fy); } ctx.closePath();
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.stroke();
    } else if (m.kind === "door") {
      const col = m.open ? t.open : t.locked;
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.strokeRect(m.x - 7, m.y - 4, 14, 8);
      ctx.fillStyle = col; ctx.fillRect(m.x - 7, m.y - 4, 14, 8);
      ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.strokeRect(m.x - 7, m.y - 4, 14, 8);
    } else if (m.kind === "switch") {
      const col = m.pressed ? t.switchOn : t.switchOff;
      ctx.beginPath(); ctx.arc(m.x, m.y, 6, 0, 2 * Math.PI);
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.stroke();
      if (m.pressed) { ctx.beginPath(); ctx.arc(m.x, m.y, 2.5, 0, 2 * Math.PI); ctx.fillStyle = t.ink; ctx.fill(); }
    } else if (m.kind === "enemy") {
      ctx.globalAlpha = m.alive ? 1 : 0.4;
      ctx.beginPath(); ctx.arc(m.x, m.y, 5, 0, 2 * Math.PI);
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke();
      if (m.alive) { ctx.fillStyle = m.color; ctx.fill(); }
      else { ctx.lineWidth = 1.8; ctx.strokeStyle = m.color; ctx.stroke(); }
      ctx.globalAlpha = 1;
    } else if (m.kind === "player") {
      const col = m.leader ? t.leader : t.player, s = m.leader ? 10 : 7;
      const h = (typeof m.heading === "number" ? m.heading : 0) * Math.PI / 180;
      const dx = VIEW.x * Math.sin(h), dy = -VIEW.z * Math.cos(h), n = Math.hypot(dx, dy) || 1;
      const ux = dx / n, uy = dy / n, nx = -uy, ny = ux;
      ctx.beginPath();
      ctx.moveTo(m.x + ux * s * 1.3, m.y + uy * s * 1.3);
      ctx.lineTo(m.x - ux * s * 0.8 + nx * s * 0.8, m.y - uy * s * 0.8 + ny * s * 0.8);
      ctx.lineTo(m.x - ux * s * 0.3, m.y - uy * s * 0.3);
      ctx.lineTo(m.x - ux * s * 0.8 - nx * s * 0.8, m.y - uy * s * 0.8 - ny * s * 0.8);
      ctx.closePath();
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke();
      ctx.fillStyle = col; ctx.fill();
      if (m.leader) { ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.stroke(); }
    }
  }
  function scaleBar(ctx, v, t, cell) {
    if (!(v.scale > 0)) return;
    const target = v.w / 4 / v.scale;                 // ~a quarter of the map wide, in world units
    const nice = [50, 100, 200, 500, 1000, 2000, 5000, 10000].find(n => n >= target * 0.7) || 10000;
    const len = nice * v.scale, x = 10, y = v.h - 12;
    ctx.lineWidth = 4; ctx.strokeStyle = t.halo; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + len, y); ctx.stroke();
    ctx.lineWidth = 2; ctx.strokeStyle = t.ink; ctx.stroke();
    ctx.font = "600 11px system-ui, sans-serif"; ctx.textBaseline = "middle";
    ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.strokeText(`${nice} u`, x + len + 6, y);
    ctx.fillStyle = t.ink; ctx.fillText(`${nice} u`, x + len + 6, y);
  }

  // ---- the feed (no DOM): polls the map model ----
  function create({ sid, api, onFrame, onStatus, visible = () => true, fast = FAST_MS, slow = SLOW_MS,
                    setTimer = setTimeout, clearTimer = clearTimeout }) {
    let model = null, stopped = false, timer = null, busy = false, fails = 0;
    async function tick() {
      timer = null;
      if (stopped || busy) return;
      busy = true; let wait = slow;
      try {
        const out = await api(`/api/pso/map/${encodeURIComponent(sid)}`);
        fails = 0;
        if (stopped) return;
        model = out && out.schema ? out : null;
        onFrame && onFrame(model);
        wait = visible() ? fast : slow;
      } catch (e) {
        fails++;
        wait = Math.min(slow * 4, fast * 2 ** Math.min(fails, 7));   // endpoint not up yet -> back off, keep trying
        onStatus && onStatus(model, String((e && e.message) || e));
      } finally { busy = false; }
      if (!stopped) timer = setTimer(tick, wait);
    }
    function poke() { if (stopped) return; clearTimer(timer); timer = null; tick(); }
    function stop() { stopped = true; clearTimer(timer); timer = null; }
    timer = setTimer(tick, 0);
    return { poke, stop, get model() { return model; } };
  }

  // ---- the section ----
  const CSS = `.psomap{display:flex;flex-direction:column;gap:6px;font-size:12px;min-width:0}
    .psomap .pm-hud{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;min-height:20px}
    .psomap .pm-where{font-weight:600}
    .psomap .pm-obj{color:var(--mut);width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .psomap .pm-obj:empty{display:none}
    .psomap .pm-stage{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:#dcdce3;touch-action:none}
    @media (prefers-color-scheme: dark){.psomap .pm-stage{background:#0e0e12}}
    .psomap canvas{display:block;width:100%;cursor:grab}
    .psomap .pm-status{position:absolute;left:8px;right:8px;top:8px;text-align:center;pointer-events:none;font-weight:600;
      color:#1b1b1f;text-shadow:0 0 3px #fff,0 0 3px #fff}
    .psomap .pm-status:empty{display:none}
    .psomap .pm-tip{position:absolute;pointer-events:none;padding:3px 7px;border-radius:6px;background:var(--bg);color:var(--fg);
      border:1px solid var(--line);box-shadow:0 4px 14px #0004;white-space:nowrap;max-width:calc(100% - 12px);overflow:hidden;text-overflow:ellipsis}
    .psomap .pm-bar{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
    .psomap .pm-bar button{font-size:11px;padding:2px 8px}
    .psomap .pm-order{color:var(--mut)}
    .psomap .pm-legend{display:flex;flex-wrap:wrap;gap:2px 10px;color:var(--mut)}
    .psomap .pm-legend span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
    .psomap .pm-sw{width:10px;height:10px;border-radius:50%;display:inline-block}`;

  function html(sid) {
    return `<details data-dock="psomap" class="sect" data-psomap="${ESC(sid)}" open hidden>` +
      `<summary draggable="true">PSO map <span class="mut">top-down · live from RAM · click to command</span></summary>` +
      `<div class="psomap">` +
      `<div class="pm-hud" role="status" aria-live="polite"><span class="pm-where" data-pm="where">–</span>` +
      `<span class="mut" data-pm="count"></span><span class="pm-obj" data-pm="objective"></span></div>` +
      `<div class="pm-stage"><canvas role="img" tabindex="0" aria-label="Top-down PSO level map"></canvas>` +
      `<div class="pm-status" data-pm="status"></div><div class="pm-tip" data-pm="tip" hidden></div></div>` +
      `<div class="mut">Double-click an open spot to send P1 there. Click a switch to press, a door to open, an enemy to attack. Wheel zooms; drag pans.</div>` +
      `<div class="pm-bar"><span class="pm-order" data-pm="order" role="status" aria-live="polite"></span>` +
      `<button type="button" class="act" data-pm="clear">Resume autonomous</button></div>` +
      `<div class="pm-legend" aria-label="Legend">` +
      `<span><i class="pm-sw" style="background:#1746c9"></i>P1 leader</span>` +
      `<span><i class="pm-sw" style="background:#2a78d6"></i>swarm</span>` +
      `<span><i class="pm-sw" style="background:#e34948"></i>enemy</span>` +
      `<span><i class="pm-sw" style="background:#eda100"></i>switch</span>` +
      `<span><i class="pm-sw" style="background:#1baf7a"></i>open</span>` +
      `<span><i class="pm-sw" style="background:#e34948"></i>locked</span>` +
      `<span><i class="pm-sw" style="background:#13b5c8"></i>exit</span></div>` +
      `</div></details>`;
  }
  function style(doc) {
    if (doc && doc.head && !doc.getElementById("pso-map-css")) {
      const st = doc.createElement("style"); st.id = "pso-map-css"; st.textContent = CSS; doc.head.append(st);
    }
  }
  function prefs() { try { return { ...JSON.parse(root.localStorage.getItem(KEY) || "{}") }; } catch { return {}; } }
  function savePrefs(o) { try { root.localStorage.setItem(KEY, JSON.stringify(o)); } catch {} }

  let current = null;
  function mount(doc, { sid, api }) {
    detach();
    style(doc);
    const sect = doc.querySelector(`details[data-dock="psomap"]`);
    if (!sect || !api) return null;
    const canvas = sect.querySelector("canvas"), stageEl = sect.querySelector(".pm-stage");
    const $ = k => sect.querySelector(`[data-pm="${k}"]`), tip = $("tip");
    let model = null, ms = [], size = { w: 0, h: 0 }, stopped = false;
    let camera = null, fitted = null, manual = false, over = false, drag = null, busyCmd = false;
    const visible = () => !stopped && sect.isConnected && sect.open && !sect.hidden && doc.visibilityState !== "hidden";

    function fit() {
      const w = Math.round(stageEl.clientWidth) || 300;
      const h = Math.round(Math.max(240, Math.min(w * 0.9, 560)));
      const dpr = Math.min(root.devicePixelRatio || 1, 3);
      if (w === size.w && h === size.h && canvas.width === Math.round(w * dpr)) return false;
      size = { w, h }; canvas.style.height = h + "px";
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      return true;
    }
    function render() {
      if (stopped || sect.hidden) return;
      fit();
      const ctx = canvas.getContext && canvas.getContext("2d");
      if (!ctx) return;
      const dpr = canvas.width / Math.max(size.w, 1);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!camera) camera = fitCamera(model);
      ms = draw(ctx, { model, view: viewOf(camera, size), theme: themeOf() });
      const where = model ? `Ep ${model.episode ?? "?"} · Floor ${model.floor ?? "?"}${model.room != null ? " · room " + model.room : ""}` : "–";
      $("where").textContent = where;
      $("count").textContent = model ? `${(model.enemies || []).filter(e => e.alive !== false).length} enemies · ${(model.players || []).length} players` : "";
      $("objective").textContent = model && model.objective ? `Objective: ${model.objective}` : "";
      $("status").textContent = model ? "" : "Waiting for the PSO map feed…";
    }
    function show(f) {
      const firstArea = f && (!model || model.fingerprint !== f.fingerprint);
      model = f;
      if (firstArea && !manual) { camera = null; fitted = f && f.fingerprint; }   // re-fit when the area changes
      if (!!f === sect.hidden) { sect.hidden = !f; root.dispatchEvent && root.dispatchEvent(new Event("resize")); }
      render();
    }
    const feed = create({ sid, api, visible, onFrame: show, onStatus: () => render() });

    function hit(e) {
      const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = null, bd = 16;
      for (const m of ms) { const d = Math.hypot(m.x - x, m.y - y); if (d < bd) { best = m; bd = d; } }
      return { best, r, x, y };
    }
    function hover(e) {
      const { best, r, x, y } = hit(e);
      tip.hidden = !best || !!drag;
      if (best) { tip.textContent = best.tip; tip.style.left = Math.min(Math.max(4, x + 12), Math.max(4, r.width - tip.offsetWidth - 4)) + "px"; tip.style.top = Math.max(4, y - 30) + "px"; }
    }
    async function order(body, label) {
      if (busyCmd || stopped) return;
      busyCmd = true; $("order").textContent = `Sending ${label}…`;
      try { await api(`/api/sessions/${encodeURIComponent(sid)}/pso-directive`, body); if (!stopped) $("order").textContent = `${label} sent.`; }
      catch (err) { if (!stopped) $("order").textContent = (err && err.message) || "Order could not be sent."; }
      finally { busyCmd = false; }
    }
    function markOrder(m) {
      if (m.kind === "switch") return order({ kind: "press", switch_id: m.id, x: m.wx, z: m.wz }, "PRESS switch");
      if (m.kind === "enemy") return order({ kind: "attack", enemy_id: m.id, x: m.wx, z: m.wz }, "ATTACK enemy");
      if (m.kind === "door") return order({ kind: "open", door_id: m.id, x: m.wx, z: m.wz }, "OPEN door");
      if (m.kind === "warp" || m.kind === "exit") return order({ kind: "goto", x: m.wx, z: m.wz, floor: model && model.floor }, "GOTO warp");
      return null;
    }
    $("clear").addEventListener("click", () => order({ kind: "clear" }, "resume autonomous"));
    canvas.addEventListener("pointerenter", () => { over = true; });
    canvas.addEventListener("pointerdown", e => {
      if (e.button !== 0 || !camera) return;
      e.preventDefault(); canvas.focus && canvas.focus({ preventScroll: true });
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, camera: { ...camera }, moved: false };
      try { canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId); } catch {} hover(e);
    });
    canvas.addEventListener("pointermove", e => {
      if (drag && drag.id === e.pointerId) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.hypot(dx, dy) > 4) drag.moved = true;
        if (drag.moved) { manual = true; camera = panView(drag.camera, size, dx, dy); render(); }
      }
      hover(e);
    });
    canvas.addEventListener("pointerup", e => {
      if (!drag || drag.id !== e.pointerId) return;
      const clicked = !drag.moved; drag = null;
      try { canvas.hasPointerCapture && canvas.hasPointerCapture(e.pointerId) && canvas.releasePointerCapture(e.pointerId); } catch {}
      if (clicked) { const m = hit(e).best; if (m) markOrder(m); }       // single click acts only on a mark
    });
    canvas.addEventListener("dblclick", e => {                           // double-click an open spot -> GOTO (RTS move)
      if (!camera) return;
      e.preventDefault();
      if (hit(e).best) return;                                           // on a mark: the single-click order already fired
      const r = canvas.getBoundingClientRect();
      const [x, z] = unproject(viewOf(camera, size), e.clientX - r.left, e.clientY - r.top);
      order({ kind: "goto", x, z, floor: model && model.floor }, "GOTO here");
    });
    const endDrag = () => { drag = null; tip.hidden = true; };
    canvas.addEventListener("pointercancel", endDrag);
    canvas.addEventListener("pointerleave", () => { over = false; tip.hidden = true; });
    canvas.addEventListener("wheel", e => {
      if (!camera || !Number.isFinite(e.deltaY) || !e.deltaY) return;
      e.preventDefault(); const r = canvas.getBoundingClientRect();
      const delta = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? size.h : 1);
      camera = zoomView(camera, size, e.clientX - r.left, e.clientY - r.top, Math.exp(Math.max(-0.7, Math.min(0.7, delta * 0.002))));
      manual = true; render();
    }, { passive: false });
    sect.addEventListener("toggle", () => { if (sect.open) { feed.poke(); render(); } });
    const onVis = () => { if (doc.visibilityState !== "hidden") feed.poke(); };
    doc.addEventListener("visibilitychange", onVis);
    const ro = root.ResizeObserver ? new root.ResizeObserver(() => { if (fit()) render(); }) : null;
    ro && ro.observe(stageEl);
    savePrefs(prefs());
    function stop() { stopped = true; feed.stop(); ro && ro.disconnect(); doc.removeEventListener("visibilitychange", onVis); if (current === ctl) current = null; }
    const ctl = { stop, render, get model() { return model; }, get view() { return camera && { ...camera }; } };
    current = ctl;
    return ctl;
  }
  function detach() { if (current) current.stop(); current = null; }

  const api = { html, mount, detach, create, viewOf, project, unproject, panView, zoomView, fitCamera,
    surfaceCells, decodeBits, marks, draw, classColor, VIEW };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxPsoMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
