// PSO interactive 2D map (operator 2026-11-02: "the bot shouldnt even need to see. the 2d map is the
// real goal - once we look at that we can point people on a 2d level where they want to go ... a
// pathfinding system where they find their way to wherever I click - double-click an area and they
// navigate to it like an RTS. If idle they continue to the portal/teleporter to leave the level"):
// a top-down map of the PSO level built ENTIRELY from the game's RAM (no vision). The PSO bot
// extracts each area's collision surface and publishes it; this renders it and steers P1 by clicks.
// It polls  GET /api/pso/map/{sid}  (the surface + live players/floor/objective/active-directive),
// drawing: the walkable collision surface as the floor (navigable cells; the void = walls); the
// gates (switches round / doors square, green = open/pressed, red/amber = locked/unpressed); the
// warps + the exit teleporter; the players (P1 the leader arrow, P2-4 the swarm); and P1's active
// GOTO target. Click to command (docs/pso-map-directives.md), writing pso-directive.json via the API:
//   double-click an open spot -> GOTO {x,z}  (RTS move; P1 A*-pathfinds there over the grid)
//   click a gate/switch        -> PRESS {flag}   (force its stage-flag: open the gate)
//   click an enemy             -> ATTACK {ptr}   (when enemies are published)
//   Resume autonomous          -> CLEAR          (P1 heads for the exit teleporter when idle)
// Zoom with the wheel, pan by dragging; it fits the area on the first frame. Hidden until a PSO
// session's first surface comes.  GBoxPsoMap.html / mount / detach / create + pure helpers.
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
  const num = v => (typeof v === "number" && isFinite(v));

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
  function fitCamera(model) {
    const b = model && model.bounds;
    if (Array.isArray(b) && b.length === 4 && b.every(Number.isFinite)) {
      return { cx: (b[0] + b[2]) / 2, cz: (b[1] + b[3]) / 2,
               radius: Math.max(b[2] - b[0], b[3] - b[1]) / 2 * 1.08 || 1000, rot: 0 };
    }
    const p = (model && model.players || []).find(q => q.slot === 1) || (model && model.players || [])[0];
    return { cx: p ? p.x : 0, cz: p ? p.z : 0, radius: 2000, rot: 0 };
  }

  // ---- the walkable surface (pure): the bot's grid cells [cx,cz] -> world rects (world = c*size) ----
  function surfaceCells(model, limit = 40000) {
    const cells = model && model.cells, size = model && model.size;
    if (!Array.isArray(cells) || !num(size) || size <= 0) return null;
    const rects = [];
    for (const c of cells) {
      if (Array.isArray(c) && c.length >= 2 && num(c[0]) && num(c[1])) {
        const x0 = c[0] * size, z0 = c[1] * size;
        rects.push([x0, z0, x0 + size, z0 + size]);
        if (rects.length >= limit) break;
      }
    }
    return { rects, cell: size };
  }

  // ---- the marks (pure): clickable/hoverable items, each projected to the canvas ----
  function marks(model, v) {
    const out = [];
    if (!model) return out;
    for (const w of model.warps || []) if (num(w.x) && num(w.z)) {
      const [x, y] = project(v, w.x, w.z);
      out.push({ kind: "warp", x, y, wx: w.x, wz: w.z, cls: w.class,
        tip: `Warp / teleporter${w.class ? " " + w.class : ""}${w.room != null ? " · room " + w.room : ""} · double-click to go` });
    }
    for (const g of model.gates || []) if (num(g.x) && num(g.z)) {
      const [x, y] = project(v, g.x, g.z);
      const isSwitch = g.kind === "switch";
      out.push({ kind: isSwitch ? "switch" : "door", x, y, wx: g.x, wz: g.z, flag: g.flag,
        set: g.set === true, hasState: typeof g.set === "boolean",
        tip: `${isSwitch ? "Switch" : "Gate"}${g.class ? " " + g.class : ""}` +
             (g.flag != null ? ` · flag ${g.flag}` : "") +
             (typeof g.set === "boolean" ? ` · ${g.set ? (isSwitch ? "pressed" : "open") : (isSwitch ? "unpressed" : "locked")}` : "") +
             (g.flag != null ? " · click to press" : "") });
    }
    for (const e of model.enemies || []) if (num(e.x) && num(e.z)) {
      const [x, y] = project(v, e.x, e.z);
      out.push({ kind: "enemy", ptr: e.ptr, x, y, wx: e.x, wz: e.z, alive: e.alive !== false, color: classColor(e.cls || e.class),
        tip: `${e.class || e.cls || "Enemy"}${e.hp != null ? " · " + e.hp + " HP" : ""}${e.alive === false ? " · dead" : ""}${e.ptr ? " · click to attack" : ""}` });
    }
    const d = model.map_directive;
    if (d && num(d.x) && num(d.z)) {
      const [x, y] = project(v, d.x, d.z);
      out.push({ kind: "goal", x, y, state: d.state, tip: `P1 ${d.op || "goto"}: ${d.state || "navigating"}` });
    }
    for (const p of model.players || []) if (num(p.x) && num(p.z)) {
      const [x, y] = project(v, p.x, p.z);
      const leader = p.slot === 1 || p.role === "leader";
      out.push({ kind: "player", slot: p.slot, x, y, leader, heading: p.heading,
        tip: `${leader ? "P1 (leader)" : "P" + (p.slot ?? "?") + " (swarm)"}${p.hp != null ? " · " + p.hp + " HP" : ""}` });
    }
    return out;
  }

  // ---- the room graph (pure): the learned plan drawn ON the map in world space ----
  // model.plan = { centroids:{room:[x,z]}, edges:{from:{door:to}}, crit_path:[...], path:[...],
  //               current_room, target_room }. Nodes = rooms at their world centroid; edges = doors;
  //               the critical path (recalled) or the visited path (first run) = the route to the goal.
  function planGraph(model, v) {
    const plan = model && model.plan;
    if (!plan || typeof plan !== "object") return null;
    const cen = plan.centroids || {};
    const pos = r => { const c = cen[r] != null ? cen[r] : cen[String(r)];
      return (Array.isArray(c) && num(c[0]) && num(c[1])) ? c : null; };
    const crit = Array.isArray(plan.crit_path) ? plan.crit_path.filter(Number.isFinite) : [];
    const trail = Array.isArray(plan.path) ? plan.path.filter(Number.isFinite) : [];
    const route = crit.length ? crit : trail;                 // recalled crit path, else the visited path
    const cur = num(plan.current_room) ? plan.current_room : null;
    const tgt = num(plan.target_room) ? plan.target_room : null;
    const goal = crit.length ? crit[crit.length - 1] : null;  // only a known exit on a recalled area
    const curIdx = cur != null ? route.indexOf(cur) : -1;
    const edges = [];
    for (const fr of Object.keys(plan.edges || {})) {
      const a = pos(fr); if (!a) continue;
      for (const to of Object.values(plan.edges[fr] || {})) {
        const b = pos(to); if (!b) continue;
        const pa = project(v, a[0], a[1]), pb = project(v, b[0], b[1]);
        edges.push([pa[0], pa[1], pb[0], pb[1]]);
      }
    }
    const routePx = [];
    for (const r of route) { const c = pos(r); if (c) routePx.push(project(v, c[0], c[1])); }
    const frontier = new Set((Array.isArray(plan.frontier) ? plan.frontier : []).filter(Number.isFinite));
    const rooms = new Set();
    for (const k of Object.keys(cen)) { const n = parseInt(k, 10); if (Number.isFinite(n)) rooms.add(n); }
    for (const r of route) rooms.add(r);
    const nodes = [];
    for (const r of rooms) {
      const c = pos(r); if (!c) continue;
      const [x, y] = project(v, c[0], c[1]);
      const idx = route.indexOf(r);
      const doors = plan.edges && (plan.edges[r] || plan.edges[String(r)]) || {};
      const hasUnexplored = Object.values(doors).some(to => frontier.has(to));   // a door out to a not-yet-entered room
      nodes.push({ x, y, room: r, current: r === cur, target: r === tgt, goal: r === goal,
        visited: curIdx >= 0 && idx >= 0 && idx < curIdx, hasUnexplored });
    }
    return { edges, route: routePx, nodes };
  }

  // ---- drawing ----
  const THEME = { void: "#121218", floor: "#e9edf5", ink: "#10131a", halo: "#ffffff", muted: "#8a8a96",
    player: "#2a78d6", leader: "#1746c9", plan: "#1baf7a", locked: "#e34948", open: "#1baf7a",
    switchOn: "#1baf7a", switchOff: "#eda100", warp: "#8a5cf6", exit: "#13b5c8",
    trail: "#9db7e8", trailLead: "#5a8ae0", node: "#c9d4e8", edge: "#6b7490" };
  function themeOf() { return THEME; }

  function draw(ctx, s) {
    const { model: m, view: v, theme: t } = s;
    ctx.save();
    ctx.fillStyle = t.void; ctx.fillRect(0, 0, v.w, v.h);
    const surf = surfaceCells(m);
    if (surf) {
      ctx.fillStyle = t.floor; ctx.globalAlpha = 0.92;
      for (const [x0, z0, x1, z1] of surf.rects) {
        const a = project(v, x0, z0), b = project(v, x1, z1);
        ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]) + 0.8, Math.abs(b[1] - a[1]) + 0.8);
      }
      ctx.globalAlpha = 1;
    }
    // Motion trails: a fading tail behind each player (world-space). The whole point of the map for
    // the operator - a dot leaving a tail is moving; a dot with no tail is sitting still.
    if (s.trails && typeof s.trails.forEach === "function") {
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      s.trails.forEach((pts, slot) => {
        if (!Array.isArray(pts) || pts.length < 2) return;
        const lead = slot === 1, col = lead ? (t.trailLead || t.leader) : (t.trail || t.player);
        ctx.lineWidth = lead ? 3.5 : 2.5; ctx.strokeStyle = col;
        for (let i = 1; i < pts.length; i++) {
          const a = project(v, pts[i - 1].x, pts[i - 1].z), b = project(v, pts[i].x, pts[i].z);
          ctx.globalAlpha = 0.1 + 0.6 * (i / pts.length);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        }
      });
      ctx.globalAlpha = 1;
    }
    // Room graph (the plan): door edges, then the critical/visited route to the goal, then room nodes.
    const pg = planGraph(m, v);
    if (pg) {
      ctx.lineWidth = 1.5; ctx.strokeStyle = t.edge || t.muted; ctx.globalAlpha = 0.55; ctx.setLineDash([]);
      for (const [ax, ay, bx, by] of pg.edges) { ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke(); }
      ctx.globalAlpha = 1;
      if (pg.route.length > 1) {
        ctx.setLineDash([]); ctx.lineCap = "round"; ctx.lineJoin = "round";
        ctx.lineWidth = 6; ctx.strokeStyle = t.halo; ctx.globalAlpha = 0.55;
        ctx.beginPath(); pg.route.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke();
        ctx.globalAlpha = 1; ctx.lineWidth = 3; ctx.strokeStyle = t.plan;
        ctx.beginPath(); pg.route.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke();
      }
      for (const n of pg.nodes) drawNode(ctx, n, t);
    }
    const ms = marks(m, v);
    // P1's active GOTO: a line from P1 to the target + a crosshair (the pathfinding result of a click)
    const goal = ms.find(k => k.kind === "goal"), p1 = ms.find(k => k.kind === "player" && k.leader);
    if (goal && p1) {
      ctx.lineWidth = 4; ctx.strokeStyle = t.halo; ctx.globalAlpha = 0.7; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(goal.x, goal.y); ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 2; ctx.strokeStyle = t.plan; ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(goal.x, goal.y); ctx.stroke(); ctx.setLineDash([]);
    }
    for (const k of ["warp", "exit", "door", "switch", "enemy", "goal", "player"]) {
      for (const mk of ms) if (mk.kind === k) drawMark(ctx, mk, t);
    }
    scaleBar(ctx, v, t);
    ctx.restore();
    return ms;
  }
  function drawMark(ctx, m, t) {
    if (m.kind === "warp" || m.kind === "exit") {
      const col = m.kind === "exit" ? t.exit : t.warp, s = m.kind === "exit" ? 9 : 7;
      ctx.beginPath(); for (let i = 0; i < 4; i++) { const a = Math.PI / 2 * i, fx = m.x + Math.cos(a) * s, fy = m.y + Math.sin(a) * s; i ? ctx.lineTo(fx, fy) : ctx.moveTo(fx, fy); } ctx.closePath();
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.stroke();
    } else if (m.kind === "door") {
      const col = !m.hasState ? t.muted : m.set ? t.open : t.locked;
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.strokeRect(m.x - 7, m.y - 4, 14, 8);
      ctx.fillStyle = col; ctx.fillRect(m.x - 7, m.y - 4, 14, 8);
      ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.strokeRect(m.x - 7, m.y - 4, 14, 8);
    } else if (m.kind === "switch") {
      const col = !m.hasState ? t.switchOff : m.set ? t.switchOn : t.switchOff;
      ctx.beginPath(); ctx.arc(m.x, m.y, 6, 0, 2 * Math.PI);
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.stroke();
      if (m.set) { ctx.beginPath(); ctx.arc(m.x, m.y, 2.5, 0, 2 * Math.PI); ctx.fillStyle = t.ink; ctx.fill(); }
    } else if (m.kind === "enemy") {
      ctx.globalAlpha = m.alive ? 1 : 0.4;
      ctx.beginPath(); ctx.arc(m.x, m.y, 5, 0, 2 * Math.PI);
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke();
      if (m.alive) { ctx.fillStyle = m.color; ctx.fill(); } else { ctx.lineWidth = 1.8; ctx.strokeStyle = m.color; ctx.stroke(); }
      ctx.globalAlpha = 1;
    } else if (m.kind === "goal") {
      ctx.strokeStyle = t.plan; ctx.lineWidth = 2; ctx.beginPath();
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { ctx.moveTo(m.x + dx * 5, m.y + dy * 5); ctx.lineTo(m.x + dx * 12, m.y + dy * 12); }
      ctx.stroke(); ctx.beginPath(); ctx.arc(m.x, m.y, 4, 0, 2 * Math.PI); ctx.fillStyle = t.plan; ctx.fill();
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
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = col; ctx.fill();
      if (m.leader) { ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.stroke(); }
    }
  }
  function drawNode(ctx, n, t) {
    const r = n.current ? 11 : n.goal ? 10 : 8;
    const fill = n.current ? t.leader : n.goal ? t.exit : (t.node || "#c9d4e8");
    ctx.globalAlpha = n.visited ? 0.55 : 1;
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke();
    ctx.fillStyle = fill; ctx.fill();
    if (n.target) { ctx.lineWidth = 2.5; ctx.strokeStyle = t.plan; ctx.beginPath(); ctx.arc(n.x, n.y, r + 3.5, 0, 2 * Math.PI); ctx.stroke(); }
    if (n.hasUnexplored) {                                            // dashed amber ring = an unexplored exit from this room
      ctx.save(); ctx.lineWidth = 2; ctx.strokeStyle = t.switchOff; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 6, 0, 2 * Math.PI); ctx.stroke(); ctx.restore();
    }
    ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = (n.current || n.goal) ? "#ffffff" : t.ink;
    ctx.font = "700 10px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(n.room), n.x, n.y);
    ctx.textAlign = "start";
  }
  function scaleBar(ctx, v, t) {
    if (!(v.scale > 0)) return;
    const target = v.w / 4 / v.scale;
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
    .psomap .pm-obj{color:var(--mut,#8a8a96);width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .psomap .pm-obj:empty{display:none}
    .psomap .pm-stage{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--line,#33384a);background:#121218;touch-action:none}
    .psomap canvas{display:block;width:100%;cursor:grab}
    .psomap .pm-status{position:absolute;left:8px;right:8px;top:8px;text-align:center;pointer-events:none;font-weight:600;
      color:#fff;text-shadow:0 0 3px #000,0 0 3px #000}
    .psomap .pm-status:empty{display:none}
    .psomap .pm-tip{position:absolute;pointer-events:none;padding:3px 7px;border-radius:6px;background:var(--bg,#1b1f29);color:var(--fg,#e7ebf3);
      border:1px solid var(--line,#33384a);box-shadow:0 4px 14px #0004;white-space:nowrap;max-width:calc(100% - 12px);overflow:hidden;text-overflow:ellipsis}
    .psomap .pm-bar{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
    .psomap .pm-bar button{font-size:11px;padding:2px 8px}
    .psomap .pm-order{color:var(--mut,#8a8a96)}
    .psomap .pm-legend{display:flex;flex-wrap:wrap;gap:2px 10px;color:var(--mut,#8a8a96)}
    .psomap .pm-legend span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
    .psomap .pm-sw{width:10px;height:10px;border-radius:50%;display:inline-block}
    .psomap .pm-banner{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 8px;font-weight:700;
      border-radius:8px;padding:6px 10px;font-size:13px;border:1px solid var(--line,#33384a);letter-spacing:.2px}
    .psomap .pm-banner small{font-weight:500;font-size:11.5px;opacity:.92}
    .psomap .pm-banner[data-state="moving"]{background:#0f7d4d;color:#fff;border-color:#0b5f3a}
    .psomap .pm-banner[data-state="stuck"]{background:#c62f2e;color:#fff;border-color:#962020;animation:pm-pulse 1.1s ease-in-out infinite}
    .psomap .pm-banner[data-state="wait"]{background:var(--bg,#1b1f29);color:var(--mut,#8a8a96)}
    @keyframes pm-pulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.25)}}
    @media (prefers-reduced-motion: reduce){.psomap .pm-banner[data-state="stuck"]{animation:none}}
    .psomap .pm-plan{display:flex;flex-wrap:wrap;align-items:center;gap:3px;font-size:11px;min-height:18px}
    .psomap .pm-plan:empty{display:none}
    .psomap .pm-room{display:inline-flex;align-items:center;justify-content:center;min-width:22px;height:19px;
      padding:0 5px;border-radius:5px;border:1px solid var(--line,#33384a);background:var(--bg,#1b1f29);color:var(--fg,#e7ebf3)}
    .psomap .pm-room.visited{background:#3a6ea52e}
    .psomap .pm-room.current{background:#1746c9;color:#fff;border-color:#1746c9;font-weight:700}
    .psomap .pm-room.target{outline:2px solid #1baf7a;outline-offset:1px}
    .psomap .pm-room.goal{background:#13b5c8;color:#07303a;border-color:#13b5c8;font-weight:700}
    .psomap .pm-arrow,.psomap .pm-note{color:var(--mut,#8a8a96)}
    .psomap .pm-cov{padding:0 6px;border-radius:9px;border:1px solid #eda100;color:#eda100;font-weight:600;white-space:nowrap}
    .psomap .pm-cov.done{border-color:#1baf7a;color:#1baf7a}`;

  function html(sid) {
    return `<details data-dock="psomap" class="sect" data-psomap="${ESC(sid)}" open hidden>` +
      `<summary draggable="true">PSO map <span class="mut">top-down · live from RAM · click to command</span></summary>` +
      `<div class="psomap">` +
      `<div class="pm-hud" role="status" aria-live="polite"><span class="pm-where" data-pm="where">–</span>` +
      `<span class="mut" data-pm="count"></span><span class="pm-obj" data-pm="objective"></span></div>` +
      `<div class="pm-banner" data-pm="banner" data-state="wait" role="status" aria-live="assertive">Waiting for the PSO map feed…</div>` +
      `<div class="pm-plan" data-pm="plan" aria-label="Run plan"></div>` +
      `<div class="pm-stage"><canvas role="img" tabindex="0" aria-label="Top-down PSO level map"></canvas>` +
      `<div class="pm-status" data-pm="status"></div><div class="pm-tip" data-pm="tip" hidden></div></div>` +
      `<div class="mut">Double-click an open spot to send P1 there. Click a gate/switch to press it, an enemy to attack. Wheel zooms; drag pans.</div>` +
      `<div class="pm-bar"><span class="pm-order" data-pm="order" role="status" aria-live="polite"></span>` +
      `<button type="button" class="act" data-pm="clear">Resume autonomous</button></div>` +
      `<div class="pm-legend" aria-label="Legend">` +
      `<span><i class="pm-sw" style="background:#1746c9"></i>P1 leader</span>` +
      `<span><i class="pm-sw" style="background:#2a78d6"></i>swarm</span>` +
      `<span><i class="pm-sw" style="background:#e34948"></i>enemy</span>` +
      `<span><i class="pm-sw" style="background:#eda100"></i>switch</span>` +
      `<span><i class="pm-sw" style="background:#1baf7a"></i>open/pressed</span>` +
      `<span><i class="pm-sw" style="background:#e34948"></i>locked</span>` +
      `<span><i class="pm-sw" style="background:#8a5cf6"></i>warp / teleporter</span></div>` +
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
    let camera = null, manual = false, over = false, drag = null, busyCmd = false;
    const visible = () => !stopped && sect.isConnected && sect.open && !sect.hidden && doc.visibilityState !== "hidden";

    // ---- motion trails + "are they moving?" detection (the operator's key signal) ----
    const trails = new Map();                      // slot -> [{x,z,t}] world-space tail
    const TRAIL_MS = 9000, TRAIL_MAX = 64, MOVE_EPS = 4;   // world units; below this over the window = not moving
    const nowMs = () => (root.performance && root.performance.now ? root.performance.now() : Date.now());
    function pushTrail(f) {
      const t0 = nowMs(), players = (f && f.players) || [];
      for (const p of players) {
        if (!(num(p.x) && num(p.z))) continue;
        let tr = trails.get(p.slot); if (!tr) trails.set(p.slot, tr = []);
        const last = tr[tr.length - 1];
        if (!last || Math.hypot(p.x - last.x, p.z - last.z) >= 0.75) tr.push({ x: p.x, z: p.z, t: t0 });
        else last.t = t0;                          // still: keep the tail point, just refresh its time
        while (tr.length > TRAIL_MAX) tr.shift();
        while (tr.length > 1 && t0 - tr[0].t > TRAIL_MS) tr.shift();
      }
      const live = new Set(players.map(p => p.slot));
      for (const slot of [...trails.keys()]) if (!live.has(slot)) trails.delete(slot);
    }
    function recentMove(slot, windowMs = 2500) {
      const tr = trails.get(slot); if (!tr || tr.length < 2) return 0;
      const cur = tr[tr.length - 1]; let ref = tr[0];
      for (let i = tr.length - 1; i >= 0; i--) { if (cur.t - tr[i].t >= windowMs) { ref = tr[i]; break; } }
      return Math.hypot(cur.x - ref.x, cur.z - ref.z);
    }
    function renderBanner() {
      const banner = $("banner"); if (!banner) return;
      const players = (model && model.players) || [], fwd = (model && model.forward) || {};
      const haveMotion = players.some(p => (trails.get(p.slot) || []).length >= 2);
      const moved = players.length ? players.reduce((m, p) => Math.max(m, recentMove(p.slot)), 0) : 0;
      const idle = haveMotion && moved < MOVE_EPS;
      let state = "wait", head, sub = "";
      if (!model || !model.live) { head = model ? "Run not live" : "Waiting for the PSO map feed…"; }
      else if (!players.length) { head = "No player positions yet…"; }
      else if (idle || fwd.stuck) {
        state = "stuck"; head = idle ? "STUCK · not moving" : "STALLED · no new room";
        const secs = num(fwd.time_since_new_room_s) ? Math.round(fwd.time_since_new_room_s) + "s stationary" : "";
        sub = [secs, fwd.fallback_target ? "→ " + fwd.fallback_target : "",
               num(fwd.fallback_dist) ? Math.round(fwd.fallback_dist) + "u to goal" : ""].filter(Boolean).join(" · ");
      } else {
        state = "moving"; head = "MOVING";
        const tgt = model.objective || (model.plan && num(model.plan.target_room) ? "room " + model.plan.target_room : "");
        sub = [tgt ? "→ " + tgt : "",
               num(fwd.time_since_new_room_s) ? Math.round(fwd.time_since_new_room_s) + "s since new room" : ""].filter(Boolean).join(" · ");
      }
      banner.dataset.state = state;
      banner.innerHTML = `<span>${ESC(head)}</span>${sub ? `<small>${ESC(sub)}</small>` : ""}`;
    }
    function renderPlan() {
      const el = $("plan"); if (!el) return;
      if (!model || !model.live) { el.innerHTML = ""; return; }
      const plan = model && model.plan, fwd = (model && model.forward) || {};
      const crit = plan && Array.isArray(plan.crit_path) ? plan.crit_path.filter(Number.isFinite) : [];
      const trail = plan && Array.isArray(plan.path) ? plan.path.filter(Number.isFinite) : [];
      const usingCrit = crit.length > 0, path = usingCrit ? crit : trail;
      const cur = plan && num(plan.current_room) ? plan.current_room
                : num(fwd.room) ? fwd.room : (model && num(model.room) ? model.room : null);
      const target = plan && num(plan.target_room) ? plan.target_room : null;
      // coverage / "fully explored" badge — how much of the reachable area has been mapped + studied
      let badge = "";
      if (plan && num(plan.coverage)) {
        const pct = Math.round(plan.coverage * 100);
        const nf = Array.isArray(plan.frontier) ? plan.frontier.length : (num(plan.frontier) ? plan.frontier : null);
        const explored = plan.explored === true || nf === 0;
        badge = ` <span class="pm-cov${explored ? " done" : ""}">${explored ? "fully explored" : pct + "% mapped" + (nf ? " · " + nf + " unexplored" : "")}</span>`;
      }
      if (!path.length) {
        const seen = num(fwd.rooms_visited) ? fwd.rooms_visited
                   : (plan && num(plan.rooms_visited) ? plan.rooms_visited : null);
        el.innerHTML = `<span class="pm-note">Exploring${num(model.floor) ? " floor " + model.floor : ""} — building the map` +
          `${seen != null ? " · " + seen + " room" + (seen === 1 ? "" : "s") + " seen" : ""}` +
          `${num(cur) ? " · in room " + cur : ""} (no learned route yet)</span>` + badge;
        return;
      }
      const curIdx = path.indexOf(cur), out = [`<span class="pm-note">${usingCrit ? "Plan:" : "Mapped:"}</span>`];
      path.forEach((r, i) => {
        const cls = ["pm-room"];
        if (r === cur) cls.push("current"); else if (curIdx >= 0 && i < curIdx) cls.push("visited");
        if (r === target) cls.push("target");
        if (usingCrit && i === path.length - 1) cls.push("goal");          // the exit is known only on a recalled area
        out.push(`<span class="${cls.join(" ")}">${usingCrit && i === path.length - 1 ? "&#9873; " : ""}${ESC(r)}</span>`);
        if (i < path.length - 1) out.push(`<span class="pm-arrow">&rsaquo;</span>`);
      });
      el.innerHTML = out.join("") + badge;
    }

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
      ms = draw(ctx, { model, view: viewOf(camera, size), theme: themeOf(), trails, now: nowMs() });
      $("where").textContent = model ? `Ep ${model.episode ?? "?"} · Floor ${model.floor ?? "?"}${model.room != null ? " · room " + model.room : ""}` : "–";
      const adv = model && model.forward && num(model.forward.floor_advances) ? ` · ${model.forward.floor_advances} floor adv` : "";
      $("count").textContent = model ? `${(model.players || []).length} players${(model.gates || []).length ? " · " + (model.gates || []).length + " gates" : ""}${(model.cells || []).length ? " · " + model.cells.length + " cells" : ""}${adv}` : "";
      $("objective").textContent = model && model.objective ? `Objective: ${model.objective}` : (model && model.map_directive ? `P1: ${model.map_directive.op || "goto"} (${model.map_directive.state || "navigating"})` : "");
      $("status").textContent = model ? (model.cells && model.cells.length ? "" : (model.players && model.players.length ? "" : "Surface not extracted yet — showing players/objective")) : "Waiting for the PSO map feed…";
      renderBanner(); renderPlan();
    }
    function show(f) {
      const newArea = f && (!model || model.fingerprint !== f.fingerprint);
      model = f;
      pushTrail(f);
      if (newArea && !manual) camera = null;              // re-fit when the area changes
      if (!!f === sect.hidden) { sect.hidden = !f; root.dispatchEvent && root.dispatchEvent(new Event("resize")); }
      render();
    }
    const feed = create({ sid, api, visible, onFrame: show, onStatus: () => render() });

    function hit(e) {
      const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = null, bd = 16;
      for (const m of ms) { if (m.kind === "goal") continue; const d = Math.hypot(m.x - x, m.y - y); if (d < bd) { best = m; bd = d; } }
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
    const scope = () => ({ room: model && model.room, episode: model && model.episode, floor: model && model.floor });
    function markOrder(m) {
      if ((m.kind === "switch" || m.kind === "door") && typeof m.flag === "number")
        return order({ op: "press", flag: m.flag, ...scope() }, `PRESS flag ${m.flag}`);
      if (m.kind === "enemy" && m.ptr) return order({ op: "attack", ptr: m.ptr, ...scope() }, "ATTACK enemy");
      if (m.kind === "warp" || m.kind === "exit") return order({ op: "goto", x: m.wx, z: m.wz, ...scope() }, "GOTO warp");
      return null;
    }
    $("clear").addEventListener("click", () => order({ op: "clear" }, "resume autonomous"));
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
      order({ op: "goto", x, z, ...scope() }, "GOTO here");
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
    surfaceCells, marks, planGraph, draw, classColor, VIEW };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxPsoMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
