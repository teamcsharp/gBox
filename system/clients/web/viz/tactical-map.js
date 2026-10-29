// Tactical map (operator 2026-10-21: "in addition to seeing the camera out crisp while we're playing the game ... a second
// camera where we're looking at the view from top down in order to have a more manageable experience ... I want Chris to
// have an awareness of where the nearest time bonus is"): a live top-down view of a Mercenaries round beside the game's
// stream, drawn by gBox from the game's own state in RAM (docs/tactical_map.md; gbox/mercs/tactical.py builds it on the
// worker), not a second in-game camera. It is a "Tactical map" section in the session's side column (drag it under the
// game like the other sections), hidden until the round's frames come; then, while it is open and on screen, it reads
//   GET /api/autoplay/tactical/{sid}?after=N    the newest frame (~8 a second; "same" when nothing moved)
//   GET /api/autoplay/tactical/stage/{key}      the stage's layout, once per stage (cached for the page's life)
// and draws: the stage's floor (the player's own level brightest, the others dimmer), its walls and its crossings (dashed: a
// ladder, a drop); the player (Chris, Barry...: ▲ his facing; a line ahead while he aims); the Majini (● alive, ◯ out of his line of sight,
// ring = attacking, dashed ring = in the way, + = the bot's target; faded with ▲/▼ on another level); the hourglasses
// (⧗ time bonus, ringed = combo bonus, hollow = taken); the bot's route (dashes) and its stand spot (ringed flag); a
// dotted line to the nearest bonus with its distance and ETA. Above it the round's clock, combo, the bot's phase
// (gather time / combo bonus / stand / break for time) and the nearest bonus; hover a mark for its details.
// Follow (centred on the player, zoomed to what matters) or Stage (all of it); Heading up turns the map with him.
//   GBoxTacticalMap.html(sid)                 the section's markup (hidden until frames come)
//   GBoxTacticalMap.mount(doc, {sid, api})    wires it; returns {stop}; detach() stops it (the view went away)
//   GBoxTacticalMap.create({sid, api, ...})   the polling without a DOM (tests)
//   GBoxTacticalMap.hud / want / viewOf / project / marks / draw    the pure parts (tests)
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const KEY = "gbox_tactical_map";             // this viewer's choices (follow / stage, heading up, zoom)
  const FAST_MS = 125, SLOW_MS = 3000, STAGE_RETRY_MS = 2000, STAGES_KEEP = 8;
  const PHASES = { gather_time: "Gather time", combo_bonus: "Combo bonus", stand: "Stand", break_for_time: "Break for time" };
  const STATES = { aim: "aiming", move: "moving", stand: "standing", grabbed: "grabbed", hit: "hit" };
  const ROUND = new Set(["playing", "dead", "paused"]);
  const PER_M = { cm: 100, mm: 1000 };
  const LEVEL_M = 1.5;                          // within this above / below the player: his own level
  const FOLLOW_M = [7, 45];                     // follow: the view's radius in metres, fitted between these
  const NEAR_FIT_M = 25;                        // follow fits the nearest bonus in when it is this near; further, an arrow
  const VIEW = { x: -1, z: 1 };                 // +z up, +x left: the right-handed world seen from above
  const stages = new Map();                     // stage key -> stage (the page's life: a stage never changes)

  // ---- words (pure) ----
  // Each enemy type its own colour (gbox/mercs/enemy_kinds.py: the RAM class), the same on every map and in the reviewer
  const KIND_COLORS = ["#e34948", "#f28e2b", "#b07aa1", "#59a14f", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
  function kindColor(cls) {
    if (!cls) return null;
    let h = 0; for (const ch of String(cls)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return KIND_COLORS[h % KIND_COLORS.length];
  }
  const enemyName = e => (e && e.kind) || "Majini";
  function phaseLabel(p) {
    if (!p) return "";
    const k = String(p).toLowerCase().replace(/[\s-]+/g, "_");
    if (PHASES[k]) return PHASES[k];
    const w = k.replace(/_/g, " ");
    return w.charAt(0).toUpperCase() + w.slice(1);
  }
  function clockText(s) {
    if (s == null || !isFinite(s)) return "–";
    s = Math.max(0, s);
    if (s < 10) return s.toFixed(1);
    return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  }
  const perM = units => PER_M[units] || 100;
  function metres(d, units) {
    if (d == null || !isFinite(d)) return "";
    const m = d / perM(units);
    return m < 10 ? `${m.toFixed(1)} m` : `${Math.round(m)} m`;
  }
  const bonusName = kind => kind === "combo" ? "Combo bonus" : "Time bonus";
  const flat = (a, b) => Math.hypot(a[0] - b[0], a[2] - b[2]);

  // what the lines above the map say (pure): clock, combo, phase, nearest bonus, target, the state of the feed
  function hud(f, now = Date.now() / 1000) {
    const out = { live: false, state: "none", screen: "", phase: "", clock: "–", combo: "", score: "", nearest: "",
                  target: "", note: "", status: "" };
    if (!f || f.seq == null) return out;
    const c = f.clock || {}, p = f.player, plan = f.plan || {}, units = f.units;
    out.screen = f.screen || "";
    out.live = f.live !== false;
    out.state = f.screen === "stopped" ? "stopped" : !out.live ? "stale" : ROUND.has(f.screen) && p ? "round" : "between";
    out.phase = phaseLabel(plan.phase);
    out.clock = clockText(c.left);
    if (c.combo) out.combo = `×${c.combo}` + (c.combo_left > 0 ? ` · ${c.combo_left.toFixed(1)} s` : "");
    if (c.score != null) out.score = `${c.score.toLocaleString("en-US")} pts` + (c.kills != null ? ` · ${c.kills} kills` : "");
    const nb = plan.nearest_bonus;
    if (nb && (nb.dist != null || nb.eta_s != null)) {
      out.nearest = [bonusName(nb.kind), metres(nb.dist, units),
                     nb.eta_s != null ? `${nb.est ? "~" : ""}${nb.eta_s.toFixed(1)} s` : ""].filter(Boolean).join(" · ");
    }
    const t = plan.target;
    if (t && p && t.pos) {
      const what = t.kind === "enemy" ? `${enemyName((f.enemies || []).find(e => e.id === t.id))} ${t.id ?? ""}`.trim() : t.kind === "bonus"
        ? bonusName((f.bonuses || []).find(b => b.id === t.id)?.kind) : t.kind === "stand" ? "Stand spot" : t.kind || "target";
      out.target = `${what} · ${metres(flat(p.pos, t.pos), units)}`;
    }
    out.note = plan.note || "";
    out.status = out.state === "stopped" ? "Autoplay stopped"
      : out.state === "stale" ? `No new frame for ${Math.round(f.age_s || 0)} s`
      : out.state === "between" ? `Between rounds${f.screen && f.screen !== "loading" ? ` · ${f.screen.replace(/_/g, " ")}` : " · loading"}` : "";
    return out;
  }

  // ---- the view (pure) ----
  function stageBounds(st) {
    const b = st && st.bounds;
    return Array.isArray(b) && b.length === 4 ? b : null;
  }
  // the view the map wants: centre, radius (world units), rotation (radians, counter-clockwise on screen)
  function want(f, st, o = {}) {
    const units = f?.units || st?.units || "cm", p = f?.player, m = perM(units), zoom = o.zoom || 1;
    const rot = o.headingUp && p && p.facing != null ? Math.atan2(VIEW.x * Math.sin(p.facing), VIEW.z * Math.cos(p.facing)) : 0;
    const b = stageBounds(st);
    if (o.mode === "stage" || !p) {
      if (b) return { cx: (b[0] + b[2]) / 2, cz: (b[1] + b[3]) / 2, radius: Math.max(b[2] - b[0], b[3] - b[1]) / 2 * 1.04, rot };
      return { cx: p ? p.pos[0] : 0, cz: p ? p.pos[2] : 0, radius: FOLLOW_M[1] * m, rot };
    }
    const plan = f.plan || {}, pts = [];
    if (plan.target?.pos) pts.push(plan.target.pos);
    for (const w of (plan.route || []).slice(0, 4)) pts.push(w);
    if (plan.nearest_bonus?.pos && flat(p.pos, plan.nearest_bonus.pos) <= NEAR_FIT_M * m) pts.push(plan.nearest_bonus.pos);
    if (plan.stand?.pos) pts.push(plan.stand.pos);
    const reach = pts.reduce((r, q) => Math.max(r, flat(p.pos, q)), 0) * 1.15;
    const radius = Math.min(FOLLOW_M[1] * m, Math.max(FOLLOW_M[0] * m, reach)) * zoom;
    // near the stage's edge the view stays over the stage (the player off centre, never off the map): more of what is there
    const keep = (c, lo, hi) => (hi - lo > 1.6 * radius ? Math.min(Math.max(c, lo + 0.8 * radius), hi - 0.8 * radius) : c);
    return { cx: b ? keep(p.pos[0], b[0], b[2]) : p.pos[0], cz: b ? keep(p.pos[2], b[1], b[3]) : p.pos[2], radius, rot };
  }
  // a canvas w x h showing the wanted view
  function viewOf(w, size) {
    return { cx: w.cx, cz: w.cz, rot: w.rot || 0, w: size.w, h: size.h, scale: Math.min(size.w, size.h) / 2 / Math.max(w.radius, 1) };
  }
  // world (x, z) -> canvas (X, Y)
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
  function zoomView(camera, size, x, y, factor, units = 'cm') {
    const before = unproject(viewOf(camera, size), x, y);
    const next = { ...camera, radius: Math.max(perM(units), Math.min(400 * perM(units), camera.radius * factor)) };
    const after = unproject(viewOf(next, size), x, y);
    next.cx += before[0] - after[0]; next.cz += before[1] - after[1];
    return next;
  }
  // a heading's direction on the canvas (unit vector)
  function screenDir(v, h) {
    const a = project(v, 0, 0), b = project(v, Math.sin(h), Math.cos(h)), dx = b[0] - a[0], dy = b[1] - a[1], n = Math.hypot(dx, dy) || 1;
    return [dx / n, dy / n];
  }
  const levelOf = (dy, units) => Math.abs(dy) <= LEVEL_M * perM(units) ? "same" : dy > 0 ? "above" : "below";

  // ---- the marks (pure): what goes where on the canvas, with each one's hover text ----
  function marks(f, v) {
    const out = [], units = f?.units || "cm", p = f?.player, plan = f?.plan || {};
    if (!f) return out;
    if (plan.trail?.length) {
      out.push({ kind: "trail", pts: plan.trail.map(w => project(v, w[0], w[2])) });
    }
    for (const hazard of plan.hazards || []) {
      const [x, y] = project(v, hazard.pos[0], hazard.pos[2]);
      const q=project(v,hazard.pos[0]+(hazard.radius||0),hazard.pos[2]);
      out.push({ kind: "hazard", x, y, radius:hazard.radius?Math.hypot(q[0]-x,q[1]-y):0,tip: hazard.reason || "Blocked approach" });
    }
    const py = p ? p.pos[1] : null, lv = q => (py == null ? "same" : levelOf(q[1] - py, units));
    const away = q => (p ? metres(flat(p.pos, q), units) : "");
    if (plan.stand?.pos) {
      const [x, y] = project(v, plan.stand.pos[0], plan.stand.pos[2]);
      out.push({ kind: "stand", x, y, r: Math.max(8, (plan.stand.r || 0) * v.scale), tip: `Stand spot · ${away(plan.stand.pos)}` });
    }
    if (p && plan.route?.length) {
      out.push({ kind: "route", pts: [project(v, p.pos[0], p.pos[2]), ...plan.route.map(w => project(v, w[0], w[2]))] });
    }
    const nb = plan.nearest_bonus, goal = plan.route?.length ? plan.route[plan.route.length - 1] : plan.target?.pos;
    if (p && nb?.pos && !(goal && flat(goal, nb.pos) < 0.5 * perM(units))) {
      out.push({ kind: "nearest", from: project(v, p.pos[0], p.pos[2]), to: project(v, nb.pos[0], nb.pos[2]) });
    }
    if (p && nb?.pos) {                          // off the map: an arrow at its edge, toward it, with how far
      const [x, y] = project(v, nb.pos[0], nb.pos[2]), pad = 16;
      if (x < pad || y < pad || x > v.w - pad || y > v.h - pad) {
        const [cx, cy] = project(v, p.pos[0], p.pos[2]), dx = x - cx, dy = y - cy;
        const k = Math.min(...[dx > 0 ? (v.w - pad - cx) / dx : dx < 0 ? (pad - cx) / dx : Infinity,
                               dy > 0 ? (v.h - pad - cy) / dy : dy < 0 ? (pad - cy) / dy : Infinity].map(q => Math.max(0, q)));
        out.push({ kind: "offscreen", x: cx + dx * k, y: cy + dy * k, dir: [dx / (Math.hypot(dx, dy) || 1), dy / (Math.hypot(dx, dy) || 1)],
                   label: metres(nb.dist ?? flat(p.pos, nb.pos), units), tip: `${bonusName(nb.kind)} off the map · ${metres(nb.dist ?? flat(p.pos, nb.pos), units)}` });
      }
    }
    for (const b of f.bonuses || []) {
      const [x, y] = project(v, b.pos[0], b.pos[2]), near = !!nb && nb.id === b.id && !b.taken;
      const label = near ? [metres(nb.dist, units), nb.eta_s != null ? `${nb.est ? "~" : ""}${nb.eta_s.toFixed(1)} s` : ""].filter(Boolean).join(" · ") : "";
      out.push({ kind: "bonus", id: b.id, x, y, type: b.kind === "combo" ? "combo" : "time", taken: !!b.taken, level: lv(b.pos), near, label,
                 tip: `${bonusName(b.kind)}${b.taken ? " (taken)" : ""} · ${away(b.pos)}${lv(b.pos) !== "same" ? ` · ${lv(b.pos)}` : ""}` });
    }
    for (const e of f.enemies || []) {
      const [x, y] = project(v, e.pos[0], e.pos[2]), fl = e.flags || [];
      const words = fl.map(k => ({ no_los: "out of sight", attacking: "attacking", blocking: "in the way", target: "the bot's target" }[k] || k));
      if (e.visibility) words.push(({ clear: "clear shot measured", blocked: "cover measured", unknown: "shot path untested" })[e.visibility] || "shot path untested");
      out.push({ kind: "enemy", id: e.id, x, y, flags: fl, level: lv(e.pos), r: Math.max(4.5, 35 * v.scale * perM(units) / 100),
                 cls: e.cls, name: e.kind, threat: e.threat, color: kindColor(e.cls),
                 tip: [`${enemyName(e)} ${e.id ?? ""}`.trim(), e.threat ? `${e.threat} threat` : "",
                       e.hp != null ? `${e.hp}${e.hp_max ? "/" + e.hp_max : ""} health` : "", away(e.pos),
                       lv(e.pos) !== "same" ? lv(e.pos) : "", ...words].filter(Boolean).join(" · ") });
    }
    for (const item of f.items || []) {
      const [x,y] = project(v,item.pos[0],item.pos[2]);
      out.push({kind:'item',id:item.id,x,y,level:lv(item.pos),tip:`${item.name || 'Recovery item'} · ${away(item.pos)}${lv(item.pos) !== 'same' ? ' · '+lv(item.pos) : ''}`});
    }
    if (plan.target?.pos && plan.target.kind !== "enemy") {
      const [x, y] = project(v, plan.target.pos[0], plan.target.pos[2]);
      out.push({ kind: "target", x, y });
    }
    if (p) {
      const [x, y] = project(v, p.pos[0], p.pos[2]);
      out.push({ kind: "player", x, y, dir: screenDir(v, p.facing || 0), aim: !!p.aim,
                 tip: ["Player", p.hp != null ? `${p.hp}${p.hp_max ? "/" + p.hp_max : ""} health` : "", STATES[p.state] || p.state || ""].filter(Boolean).join(" · ") });
    }
    return out;
  }

  // ---- drawing ----
  const THEME_VARS = { void: "--tm-void", floor: "--tm-floor", floorOther: "--tm-floor-other", wall: "--tm-wall",
    wallOther: "--tm-wall-other", cross: "--tm-cross", player: "--tm-player", enemy: "--tm-enemy", bonus: "--tm-bonus",
    plan: "--tm-plan", ink: "--tm-ink", halo: "--tm-halo", muted: "--tm-muted" };
  const THEME_LIGHT = { void: "#dcdce3", floor: "#ffffff", floorOther: "#ececf0", wall: "#5d5d68", wallOther: "#c2c2ca",
    cross: "#8a8a96", player: "#2a78d6", enemy: "#e34948", bonus: "#eda100", plan: "#1baf7a", ink: "#1b1b1f", halo: "#ffffff", muted: "#8a8a96" };
  function themeOf(el) {
    const cs = el && root.getComputedStyle ? root.getComputedStyle(el) : null, t = {};
    for (const [k, name] of Object.entries(THEME_VARS)) t[k] = (cs && cs.getPropertyValue(name).trim()) || THEME_LIGHT[k];
    return t;
  }

  // the stage: the floor in three fills (below / the player's level / above), walls, crossings
  function drawStage(ctx, st, v, py, t) {
    if (!st || st.kind !== "mesh" || !Array.isArray(st.points) || !Array.isArray(st.tris)) return;
    const P = st.points, T = st.tris, n = P.length / 3, units = st.units || "cm", lim = LEVEL_M * perM(units);
    const sx = new Float32Array(n), sy = new Float32Array(n);
    for (let i = 0; i < n; i++) { const q = project(v, P[3 * i], P[3 * i + 2]); sx[i] = q[0]; sy[i] = q[1]; }
    const bucket = y => (py == null || Math.abs(y - py) <= lim ? 1 : y < py ? 0 : 2);
    const fills = [t.floorOther, t.floor, t.floorOther], alpha = [0.85, 1, 0.55];
    for (const k of [0, 1, 2]) {
      ctx.beginPath();
      let any = false;
      for (let i = 0; i + 2 < T.length; i += 3) {
        const a = T[i], b = T[i + 1], c = T[i + 2];
        if (bucket((P[3 * a + 1] + P[3 * b + 1] + P[3 * c + 1]) / 3) !== k) continue;
        ctx.moveTo(sx[a], sy[a]); ctx.lineTo(sx[b], sy[b]); ctx.lineTo(sx[c], sy[c]); ctx.closePath();
        any = true;
      }
      if (!any) continue;
      ctx.globalAlpha = alpha[k]; ctx.fillStyle = fills[k]; ctx.fill();
      ctx.lineWidth = 0.6; ctx.strokeStyle = fills[k]; ctx.stroke();        // seals the hairlines between triangles
    }
    ctx.globalAlpha = 1;
    const edges = (list, same, style, width, dash) => {
      if (!Array.isArray(list) || !list.length) return;
      ctx.beginPath();
      for (let i = 0; i + 1 < list.length; i += 2) {
        const a = list[i], b = list[i + 1];
        if ((bucket((P[3 * a + 1] + P[3 * b + 1]) / 2) === 1) !== same) continue;
        ctx.moveTo(sx[a], sy[a]); ctx.lineTo(sx[b], sy[b]);
      }
      ctx.setLineDash(dash); ctx.lineWidth = width; ctx.strokeStyle = style; ctx.stroke(); ctx.setLineDash([]);
    };
    edges(st.walls, false, t.wallOther, 1, []);
    edges(st.cross, false, t.wallOther, 1, [3, 3]);
    edges(st.walls, true, t.wall, 1.5, []);
    edges(st.cross, true, t.cross, 1.5, [4, 3]);
    for (const c of st.climbs || []) {                // ladders and drops: where a level is left or reached
      const [x, y] = project(v, c[0], c[1]), mine = py == null || Math.abs(c[2] - py) <= lim || Math.abs(c[3] - py) <= lim;
      ladder(ctx, x, y, mine ? t.wall : t.wallOther, t);       // bright where it leaves or reaches his level
    }
  }
  function ladder(ctx, x, y, ink, t) {
    ctx.beginPath();
    ctx.moveTo(x - 2.5, y - 4); ctx.lineTo(x - 2.5, y + 4); ctx.moveTo(x + 2.5, y - 4); ctx.lineTo(x + 2.5, y + 4);
    for (const r of [-1.5, 1.5]) { ctx.moveTo(x - 2.5, y + r); ctx.lineTo(x + 2.5, y + r); }
    ctx.lineWidth = 2.6; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.lineWidth = 1; ctx.strokeStyle = ink; ctx.stroke();
  }

  function hourglass(ctx, x, y, s) {
    ctx.beginPath();
    ctx.moveTo(x - s * 0.62, y - s); ctx.lineTo(x + s * 0.62, y - s); ctx.lineTo(x, y);
    ctx.lineTo(x + s * 0.62, y + s); ctx.lineTo(x - s * 0.62, y + s); ctx.lineTo(x, y); ctx.closePath();
  }
  function label(ctx, text, x, y, t) {
    ctx.font = "600 11px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.strokeText(text, x, y);
    ctx.fillStyle = t.ink; ctx.fillText(text, x, y);
  }
  function caret(ctx, m, t) {
    if (m.level === "same") return;
    ctx.fillStyle = t.ink; ctx.beginPath();
    const x = m.x + 8, y = m.y - 7, up = m.level === "above";
    ctx.moveTo(x - 3.5, up ? y + 2 : y - 2); ctx.lineTo(x + 3.5, up ? y + 2 : y - 2); ctx.lineTo(x, up ? y - 3 : y + 3); ctx.closePath(); ctx.fill();
  }

  // the whole map: stage, plan, bonuses, Majini, the player, the scale; returns the marks (for hovering)
  function draw(ctx, s) {
    const { frame: f, stage: st, view: v, theme: t } = s;
    ctx.save();
    ctx.fillStyle = t.void; ctx.fillRect(0, 0, v.w, v.h);
    const p = f && f.player, units = (f && f.units) || (st && st.units) || "cm";
    if (st && st.units === units) drawStage(ctx, st, v, p ? p.pos[1] : null, t);
    const ms = marks(f, v);
    for (const c of (st && st.units === units && st.climbs) || []) {
      const [x, y] = project(v, c[0], c[1]);
      ms.push({ kind: "climb", x, y, tip: `Ladder or drop · ${metres(c[3] - c[2], units)} from ${metres(c[2], units)} to ${metres(c[3], units)} up` });
    }
    for (const m of ms) {
      if (m.kind === "stand") {
        ctx.lineWidth = 2; ctx.strokeStyle = t.plan; ctx.setLineDash([]);
        ctx.beginPath(); ctx.arc(m.x, m.y, m.r, 0, 2 * Math.PI); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(m.x, m.y); ctx.lineTo(m.x, m.y - 12); ctx.lineTo(m.x + 8, m.y - 9); ctx.lineTo(m.x, m.y - 6);
        ctx.fillStyle = t.plan; ctx.fill(); ctx.stroke();
      } else if (m.kind === "hazard") {
        ctx.strokeStyle = "#ff554d"; ctx.lineWidth = 2; ctx.setLineDash([]);
        ctx.beginPath(); ctx.arc(m.x, m.y, 6, 0, Math.PI * 2); ctx.stroke();
        if(m.radius){ctx.setLineDash([3,3]);ctx.beginPath();ctx.arc(m.x,m.y,Math.max(6,m.radius),0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);}
      } else if (m.kind === "trail") {
        ctx.strokeStyle = "#42bfd9"; ctx.lineWidth = 1.5; ctx.setLineDash([]);
        ctx.beginPath(); m.pts.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.stroke();
      } else if (m.kind === "route") {
        ctx.lineWidth = 4; ctx.strokeStyle = t.halo; ctx.globalAlpha = 0.7; ctx.setLineDash([]);
        ctx.beginPath(); m.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
        ctx.globalAlpha = 1; ctx.lineWidth = 2; ctx.strokeStyle = t.plan; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = t.plan;
        for (const [x, y] of m.pts.slice(1, -1)) { ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 2 * Math.PI); ctx.fill(); }
      } else if (m.kind === "nearest") {
        ctx.lineWidth = 1.5; ctx.strokeStyle = t.bonus; ctx.setLineDash([2, 4]);
        ctx.beginPath(); ctx.moveTo(m.from[0], m.from[1]); ctx.lineTo(m.to[0], m.to[1]); ctx.stroke(); ctx.setLineDash([]);
      } else if (m.kind === "offscreen") {
        const [dx, dy] = m.dir, nx = -dy, ny = dx;
        ctx.beginPath(); ctx.moveTo(m.x + dx * 8, m.y + dy * 8);
        ctx.lineTo(m.x - dx * 5 + nx * 6, m.y - dy * 5 + ny * 6); ctx.lineTo(m.x - dx * 5 - nx * 6, m.y - dy * 5 - ny * 6); ctx.closePath();
        ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = t.bonus; ctx.fill();
        const tw = (ctx.measureText ? ctx.measureText(m.label).width : 30) || 30;
        label(ctx, m.label, Math.min(Math.max(4, m.x - dx * 14 - tw / 2), v.w - tw - 4), Math.min(Math.max(10, m.y - dy * 16), v.h - 10), t);
      }
    }
    for (const m of ms) {
      if (m.kind === 'item') {
        ctx.globalAlpha = m.level === 'same' ? 1 : .55;
        ctx.fillStyle = t.halo; ctx.fillRect(m.x-6,m.y-6,12,12);
        ctx.fillStyle = t.plan; ctx.fillRect(m.x-2,m.y-5,4,10); ctx.fillRect(m.x-5,m.y-2,10,4);
        ctx.globalAlpha = 1;
      }
      if (m.kind !== "bonus") continue;
      ctx.globalAlpha = m.taken ? 0.45 : m.level === "same" ? 1 : 0.55;
      hourglass(ctx, m.x, m.y, m.near ? 7.5 : 6.5);
      if (m.taken) { ctx.lineWidth = 1.5; ctx.strokeStyle = t.muted; ctx.stroke(); }
      else { ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = t.bonus; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = t.ink; ctx.stroke(); }
      if (m.type === "combo") { ctx.lineWidth = 2; ctx.strokeStyle = m.taken ? t.muted : t.bonus; ctx.beginPath(); ctx.arc(m.x, m.y, 10.5, 0, 2 * Math.PI); ctx.stroke(); }
      ctx.globalAlpha = 1;
      if (!m.taken) caret(ctx, m, t);
      if (m.label) {                                  // right of it, or left when the edge is near
        const tw = (ctx.measureText ? ctx.measureText(m.label).width : 60) || 60;
        label(ctx, m.label, m.x + 12 + tw > v.w - 4 ? m.x - 12 - tw : m.x + 12, m.y + 1, t);
      }
    }
    for (const m of ms) {
      if (m.kind !== "enemy") continue;
      const fl = new Set(m.flags);
      ctx.globalAlpha = m.level === "same" ? 1 : 0.5;
      ctx.beginPath(); ctx.arc(m.x, m.y, m.r, 0, 2 * Math.PI);
      ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke();
      const ink = m.color || t.enemy;
      if (fl.has("no_los")) { ctx.lineWidth = 2; ctx.strokeStyle = ink; ctx.stroke(); }
      else { ctx.fillStyle = ink; ctx.fill(); }
      if (fl.has("attacking")) { ctx.lineWidth = 2; ctx.strokeStyle = ink; ctx.beginPath(); ctx.arc(m.x, m.y, m.r + 4, 0, 2 * Math.PI); ctx.stroke(); }
      if (fl.has("blocking")) { ctx.lineWidth = 2; ctx.strokeStyle = t.plan; ctx.setLineDash([3, 2]); ctx.beginPath(); ctx.arc(m.x, m.y, m.r + 4, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]); }
      if (fl.has("target")) {
        const r = m.r + 7; ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.beginPath();
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { ctx.moveTo(m.x + dx * (r - 4), m.y + dy * (r - 4)); ctx.lineTo(m.x + dx * (r + 3), m.y + dy * (r + 3)); }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      caret(ctx, m, t);
    }
    for (const m of ms) {
      if (m.kind === "target") {
        ctx.lineWidth = 1.5; ctx.strokeStyle = t.ink; ctx.beginPath();
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { ctx.moveTo(m.x + dx * 9, m.y + dy * 9); ctx.lineTo(m.x + dx * 15, m.y + dy * 15); }
        ctx.stroke();
      } else if (m.kind === "player") {
        const [dx, dy] = m.dir, nx = -dy, ny = dx, s = 9;
        if (m.aim) {
          ctx.lineWidth = 1.5; ctx.strokeStyle = t.player; ctx.globalAlpha = 0.7; ctx.beginPath();
          const reach = Math.min(Math.min(v.w, v.h) * 0.45, 12 * perM(units) * v.scale);   // 12 m of his aim
          ctx.moveTo(m.x + dx * s, m.y + dy * s); ctx.lineTo(m.x + dx * Math.max(reach, s * 2), m.y + dy * Math.max(reach, s * 2)); ctx.stroke(); ctx.globalAlpha = 1;
        }
        ctx.beginPath();
        ctx.moveTo(m.x + dx * s * 1.3, m.y + dy * s * 1.3);
        ctx.lineTo(m.x - dx * s * 0.8 + nx * s * 0.85, m.y - dy * s * 0.8 + ny * s * 0.85);
        ctx.lineTo(m.x - dx * s * 0.35, m.y - dy * s * 0.35);
        ctx.lineTo(m.x - dx * s * 0.8 - nx * s * 0.85, m.y - dy * s * 0.8 - ny * s * 0.85);
        ctx.closePath();
        ctx.lineWidth = 3; ctx.strokeStyle = t.halo; ctx.stroke(); ctx.fillStyle = t.player; ctx.fill();
      }
    }
    scaleBar(ctx, v, units, t);
    ctx.restore();
    return ms;
  }

  // a round length in metres about a quarter of the map wide, bottom left
  function scaleBar(ctx, v, units, t) {
    const pxPerM = v.scale * perM(units);
    if (!(pxPerM > 0)) return;
    const target = v.w / 4 / pxPerM, nice = [1, 2, 5, 10, 20, 50, 100].find(n => n >= target * 0.7) || 100, len = nice * pxPerM;
    const x = 10, y = v.h - 12;
    ctx.lineWidth = 4; ctx.strokeStyle = t.halo; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + len, y); ctx.stroke();
    ctx.lineWidth = 2; ctx.strokeStyle = t.ink; ctx.stroke();
    label(ctx, `${nice} m`, x + len + 6, y, t);
  }

  // ---- the feed (no DOM): polls the frames, fetches each stage once ----
  function create({ sid, api, onFrame, onStage, onStatus, visible = () => true, fast = FAST_MS, slow = SLOW_MS,
                    setTimer = setTimeout, clearTimer = clearTimeout, now = () => Date.now() }) {
    let seq = null, frame = null, stopped = false, timer = null, busy = false, fails = 0, stageKey = null, stageFailed = 0;
    async function loadStage(key) {
      if (stages.has(key)) { stageKey = key; return onStage && onStage(stages.get(key)); }
      if (key === stageKey || now() - stageFailed < STAGE_RETRY_MS) return;
      stageKey = key;
      try {
        const st = await api(`/api/autoplay/tactical/stage/${encodeURIComponent(key)}`);
        stages.set(key, st);
        while (stages.size > STAGES_KEEP) stages.delete(stages.keys().next().value);
        if (!stopped && key === stageKey && onStage) onStage(st);
      } catch { if (key === stageKey) { stageKey = null; stageFailed = now(); } }   // tried again with a later frame
    }
    async function tick() {
      timer = null;
      if (stopped || busy) return;
      busy = true;
      let wait = slow;
      try {
        const out = await api(`/api/autoplay/tactical/${encodeURIComponent(sid)}${seq != null ? `?after=${seq}` : ""}`);
        fails = 0;
        if (stopped) return;
        if (out && out.seq != null) {
          if (out.same) { if (frame) { frame = { ...frame, age_s: out.age_s, live: out.live }; onStatus && onStatus(frame); } }
          else { frame = out; seq = out.seq; onFrame && onFrame(frame); }
          if (frame && frame.stage && (frame.stage !== stageKey || !stages.has(frame.stage))) loadStage(frame.stage);
          wait = visible() ? fast : slow;
        } else if (frame) { frame = null; seq = null; onFrame && onFrame(null); }   // the frames are gone (no round for a while)
      } catch (e) {
        fails++;
        wait = Math.min(slow * 4, fast * 2 ** Math.min(fails, 8));
        onStatus && onStatus(frame, String((e && e.message) || e));
      } finally { busy = false; }
      if (!stopped) timer = setTimer(tick, wait);
    }
    function poke() { if (stopped) return; clearTimer(timer); timer = null; tick(); }
    function stop() { stopped = true; clearTimer(timer); timer = null; }
    timer = setTimer(tick, 0);
    return { poke, stop, get frame() { return frame; } };
  }

  // ---- the section ----
  const CSS = `.tmap{--tm-void:#dcdce3;--tm-floor:#fff;--tm-floor-other:#ececf0;--tm-wall:#5d5d68;--tm-wall-other:#c2c2ca;
      --tm-cross:#8a8a96;--tm-player:#2a78d6;--tm-enemy:#e34948;--tm-bonus:#eda100;--tm-plan:#1baf7a;--tm-ink:#1b1b1f;
      --tm-halo:#fff;--tm-muted:#8a8a96;display:flex;flex-direction:column;gap:6px;font-size:12px;min-width:0}
    @media (prefers-color-scheme: dark){.tmap{--tm-void:#0e0e12;--tm-floor:#3b3b47;--tm-floor-other:#25252d;--tm-wall:#a4a4b0;
      --tm-wall-other:#4a4a55;--tm-cross:#7d7d8a;--tm-player:#3987e5;--tm-enemy:#e34948;--tm-bonus:#c98500;--tm-plan:#199e70;
      --tm-ink:#e8e8ee;--tm-halo:#101014;--tm-muted:#7d7d8a}}
    :root[data-embedded="true"] .tmap{--tm-void:#0e0e12;--tm-floor:#3b3b47;--tm-floor-other:#25252d;--tm-wall:#a4a4b0;
      --tm-wall-other:#4a4a55;--tm-cross:#7d7d8a;--tm-player:#3987e5;--tm-enemy:#e34948;--tm-bonus:#c98500;--tm-plan:#199e70;
      --tm-ink:#e8e8ee;--tm-halo:#101014;--tm-muted:#7d7d8a}
    .tmap .tm-hud{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;min-height:22px}
    .tmap .tm-clock{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1}
    .tmap .tm-phase{padding:1px 8px;border:1px solid var(--line);border-radius:999px;background:var(--card);font-weight:600;white-space:nowrap}
    .tmap .tm-phase:empty,.tmap .tm-line:empty{display:none}
    .tmap .tm-line{width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .tmap .tm-stage{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:var(--tm-void);touch-action:none}
    .tmap canvas{display:block;width:100%}
    .tmap .tm-status{position:absolute;left:8px;right:8px;top:8px;text-align:center;pointer-events:none;font-weight:600;color:var(--tm-ink);
      text-shadow:0 0 3px var(--tm-halo),0 0 3px var(--tm-halo)}
    .tmap .tm-status:empty{display:none}
    .tmap .tm-tip{position:absolute;pointer-events:none;padding:3px 7px;border-radius:6px;background:var(--bg);color:var(--fg);
      border:1px solid var(--line);box-shadow:0 4px 14px #0004;white-space:nowrap;max-width:calc(100% - 12px);overflow:hidden;text-overflow:ellipsis}
    .tmap .tm-bar{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
    .tmap .tm-bar button{font-size:11px;padding:2px 8px}
    .tmap .tm-bar button[aria-pressed=true]{border-color:var(--acc);color:var(--acc)}
    .tmap .tm-legend{display:flex;flex-wrap:wrap;gap:2px 10px;color:var(--mut)}
    .tmap .tm-legend span{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
    .tmap .tm-legend svg{flex:none}
    .tmap .tm-kinds{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:4px}
    .tmap .tm-kind{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
    .tmap .tm-kind img,.tmap .tm-kind .tm-face{width:30px;height:30px;border-radius:50%;object-fit:cover;flex:none;border:2px solid var(--kc)}
    .tmap .tm-kind .tm-face{display:inline-grid;place-items:center;background:var(--kc);color:#fff;font:700 11px system-ui}
    .tmap .tm-kind small{color:var(--mut)}`;

  const ICON = {
    player: `<svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1l4.5 9.5L6 8 1.5 10.5z" fill="var(--tm-player)"/></svg>`,
    enemy: `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4" fill="var(--tm-enemy)"/></svg>`,
    hidden: `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="3.6" fill="none" stroke="var(--tm-enemy)" stroke-width="1.6"/></svg>`,
    attack: `<svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="3.2" fill="var(--tm-enemy)"/><circle cx="7" cy="7" r="5.8" fill="none" stroke="var(--tm-enemy)" stroke-width="1.4"/></svg>`,
    time: `<svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 1h7L6 6l3.5 5h-7L6 6z" fill="var(--tm-bonus)" stroke="var(--tm-ink)" stroke-width=".6"/></svg>`,
    combo: `<svg width="14" height="14" viewBox="0 0 14 14"><path d="M4.5 3.5h5L7 7l2.5 3.5h-5L7 7z" fill="var(--tm-bonus)"/><circle cx="7" cy="7" r="6" fill="none" stroke="var(--tm-bonus)" stroke-width="1.4"/></svg>`,
    route: `<svg width="16" height="12" viewBox="0 0 16 12"><path d="M1 6h14" stroke="var(--tm-plan)" stroke-width="2" stroke-dasharray="4 3"/></svg>`,
    stand: `<svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.6" fill="none" stroke="var(--tm-plan)" stroke-width="1.6"/></svg>`,
    climb: `<svg width="10" height="12" viewBox="0 0 10 12"><path d="M2 1v10M8 1v10M2 3.5h6M2 6.5h6M2 9.5h6" stroke="var(--tm-wall)" stroke-width="1.3" fill="none"/></svg>`
  };

  function html(sid) {
    return `<details data-dock="tactical" class="sect" data-tmap="${ESC(sid)}" open hidden>` +
      `<summary draggable="true">Tactical map <span class="mut">top-down · live from the game's RAM</span></summary>` +
      `<div class="tmap">` +
      `<div class="tm-hud" role="status" aria-live="polite"><span class="tm-clock" data-tm="clock" title="Time left in the round">–</span>` +
      `<span class="tm-phase" data-tm="phase" title="What the bot is doing"></span><span data-tm="combo" title="Combo and its window"></span>` +
      `<span class="mut" data-tm="score"></span><span class="tm-line" data-tm="nearest" title="The nearest time bonus: distance along the route and time to reach it"></span>` +
      `<span class="tm-line mut" data-tm="target"></span></div>` +
      `<div class="tm-bar" role="toolbar" aria-label="Tactical map view">` +
      `<button class="act" type="button" data-tm-mode="follow" aria-pressed="true" title="Centred on the player, zoomed to what he is going for">Follow</button>` +
      `<button class="act" type="button" data-tm-mode="stage" aria-pressed="false" title="The whole stage">Stage</button>` +
      `<button class="act" type="button" data-tm-heading aria-pressed="false" title="Turn the map with the player: his facing is up">Heading up</button>` +
      `<button class="act" type="button" data-tm-zoom="out" aria-label="Zoom out" title="Zoom out">−</button>` +
      `<button class="act" type="button" data-tm-zoom="in" aria-label="Zoom in" title="Zoom in">+</button></div>` +
      `<div class="tm-stage"><canvas role="img" tabindex="0" style="touch-action:none;cursor:grab" aria-label="Top-down map of the round"></canvas><div class="tm-status" data-tm="status"></div>` +
      `<div class="tm-tip" data-tm="tip" hidden></div></div>` +
      `<div class="mut" data-tm="interaction">Hover to hold the view. Wheel to zoom; drag to pan. Follow resumes tracking.</div>` +
      `<div class="tm-bar" data-tm="goal-box" hidden><span data-tm="goal" role="status" aria-live="polite"></span><button type="button" class="act" data-tm="cancel-goal">Cancel goal</button></div>` +
      `<div class="tm-legend" aria-label="Legend"><span>${ICON.player}Player</span><span>${ICON.enemy}Majini</span>` +
      `<span>${ICON.hidden}out of sight</span><span>${ICON.attack}attacking</span><span>${ICON.time}time bonus</span>` +
      `<span>${ICON.combo}combo bonus</span><span>${ICON.route}route</span><span>${ICON.stand}stand spot</span>` +
      `<span>${ICON.climb}ladder / drop</span></div>` +
      `<div class="tm-kinds" data-tm="kinds" aria-label="Enemies on the map"></div>` +
      `</div></details>`;
  }

  function style(doc) {
    if (doc && doc.head && !doc.getElementById("tactical-map-css")) {
      const st = doc.createElement("style"); st.id = "tactical-map-css"; st.textContent = CSS; doc.head.append(st);
    }
  }

  function prefs() {
    try { return { mode: "follow", headingUp: false, zoom: 1, ...JSON.parse(root.localStorage.getItem(KEY) || "{}") }; }
    catch { return { mode: "follow", headingUp: false, zoom: 1 }; }
  }
  function savePrefs(o) { try { root.localStorage.setItem(KEY, JSON.stringify(o)); } catch {} }

  let current = null;
  // The legend of the enemy types on the map (frame.kinds): each with its portrait (gbox/tactical_map.py: captured from
  // the game while the bot's laser sat on one) or its initials until one is captured, its colour, count and threat.
  function kindsHtml(f, portrait) {
    const kinds = Object.entries((f && f.kinds) || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
    return kinds.map(([cls, k]) => {
      const c = kindColor(cls), name = k.name || cls, src = portrait ? portrait(f.title, cls) : "";
      const face = `<span class="tm-face" aria-hidden="true">${ESC(name.slice(0, 2).toUpperCase())}</span>`;
      const pic = src ? `<img alt="" src="${ESC(src)}" data-face="${ESC(name.slice(0, 2).toUpperCase())}">` : face;
      return `<span class="tm-kind" style="--kc:${c}" title="${ESC(cls)}">${pic}<span>${ESC(name)} ×${k.count || 0}` +
        (k.threat ? ` <small>${ESC(k.threat)} threat</small>` : "") + `</span></span>`;
    }).join("");
  }
  function mount(doc, { sid, api, ...opts }) {
    detach();
    style(doc);
    const sect = doc.querySelector(`details[data-dock="tactical"]`);
    if (!sect || !api) return null;
    const box = sect.querySelector(".tmap"), canvas = sect.querySelector("canvas"), stageEl = sect.querySelector(".tm-stage");
    const $ = k => sect.querySelector(`[data-tm="${k}"]`), tip = $("tip");
    const o = prefs();
    let frame = null, stage = null, ms = [], radius = null, size = { w: 0, h: 0 }, stopped = false, lastSeq = null;
    let camera = null, held = null, manual = false, over = false, drag = null, goalBusy = false;
    const visible = () => !stopped && sect.isConnected && sect.open && !sect.hidden && doc.visibilityState !== "hidden";

    function fit() {
      const w = Math.round(stageEl.clientWidth) || 300;
      const h = Math.round(Math.max(220, Math.min(w * 0.85, 560)));
      const dpr = Math.min(root.devicePixelRatio || 1, 3);
      if (w === size.w && h === size.h && canvas.width === Math.round(w * dpr)) return false;
      size = { w, h };
      canvas.style.height = h + "px";
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
      const w = held || want(frame, stage, o);
      radius = held ? w.radius : radius == null || o.mode === "stage" || frame?.seq !== lastSeq && Math.abs(w.radius - radius) / w.radius > 0.6
        ? w.radius : radius + (w.radius - radius) * 0.35;
      lastSeq = frame?.seq;
      camera = { ...w, radius };
      ms = draw(ctx, { frame, stage, view: viewOf(camera, size), theme: themeOf(box) });
      const h = hud(frame);
      $("clock").textContent = h.clock; $("phase").textContent = h.phase; $("combo").textContent = h.combo;
      $("score").textContent = h.score; $("status").textContent = h.status;
      const kinds = kindsHtml(frame, opts.portrait), kindsBox = $("kinds");
      if (kindsBox && kindsBox.dataset.html !== kinds) {          // only when the types or counts change: no image flicker
        kindsBox.dataset.html = kinds; kindsBox.innerHTML = kinds;
        kindsBox.querySelectorAll("img[data-face]").forEach(img => { img.onerror = () => {
          const f = doc.createElement("span"); f.className = "tm-face"; f.textContent = img.dataset.face; img.replaceWith(f); }; });
      }
      $("nearest").textContent = h.nearest ? `Nearest: ${h.nearest}` : "";
      $("target").textContent = [h.target && `Target: ${h.target}`, h.note].filter(Boolean).join(" · ");
      const goal = frame?.operator_goal;
      if (goal && !goalBusy) goalMessage(`${goal.label || 'Map goal'}: ${goal.state}${goal.reason ? ' · ' + goal.reason : ''}`, !['completed','cancelled','expired','unavailable','observed_removed'].includes(goal.state));
      canvas.setAttribute("aria-label", `Top-down map: ${(frame?.enemies || []).length} Majini, ` +
        `${(frame?.bonuses || []).filter(b => !b.taken).length} bonuses left` + (h.nearest ? `; nearest ${h.nearest}` : ""));
    }
    function show(f) {
      if (frame && (!f || f.stage !== frame.stage || f.goal_round !== frame.goal_round)) {
        held = null; manual = false; drag = null; $("goal-box").hidden = true;
      }
      frame = f;
      if (!!f === sect.hidden) {                      // frames came (a round of a Mercenaries title), or went for good
        sect.hidden = !f;
        root.dispatchEvent && root.dispatchEvent(new Event("resize"));
      }
      render();
    }
    const feed = create({ sid, api, visible, ...opts, onFrame: show, onStage: st => { stage = st; render(); },
                          onStatus: f => { if (f) { frame = f; render(); } } });

    function paintButtons() {
      sect.querySelectorAll("[data-tm-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.tmMode === o.mode)));
      sect.querySelector("[data-tm-heading]").setAttribute("aria-pressed", String(!!o.headingUp));
    }
    sect.querySelector(".tm-bar").addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.tmMode) o.mode = b.dataset.tmMode;
      else if (b.hasAttribute("data-tm-heading")) o.headingUp = !o.headingUp;
      else if (b.dataset.tmZoom) { o.zoom = Math.min(4, Math.max(0.25, (o.zoom || 1) * (b.dataset.tmZoom === "in" ? 1 / 1.4 : 1.4))); if (o.mode === "stage") o.mode = "follow"; }
      held = null; manual = false; radius = null; savePrefs(o); paintButtons(); render();
      if (over && camera) held = { ...camera };
    });
    paintButtons();
    function hit(e) {
      const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      let best = null, bd = 16;
      for (const m of ms) {
        if (!m.tip) continue;
        const d = Math.hypot(m.x - x, m.y - y);
        if (d < bd) { best = m; bd = d; }
      }
      return { best, r, x, y };
    }
    function hover(e) {
      const {best,r,x,y} = hit(e);
      tip.hidden = !best || !!drag?.moved;
      if (best) {
        tip.textContent = best.tip;
        const left = Math.min(Math.max(4, x + 12), Math.max(4, r.width - tip.offsetWidth - 4));
        tip.style.left = left + "px"; tip.style.top = Math.max(4, y - 30) + "px";
      }
    }
    function goalMessage(message, cancellable = false) {
      $("goal-box").hidden = false; $("goal").textContent = message; $("cancel-goal").hidden = !cancellable;
    }
    async function command(body, label) {
      if (goalBusy || stopped) return;
      goalBusy = true; const round = frame?.goal_round;
      goalMessage(`Requesting ${label}…`);
      try {
        const reply = await api(`/api/autoplay/tactical/${encodeURIComponent(sid)}/goal`, body);
        if (stopped || round !== frame?.goal_round) return;
        goalMessage(`${reply.label || label}: ${reply.state || 'queued'}`, reply.state === 'queued');
      } catch (e) { if (!stopped && round === frame?.goal_round) goalMessage(e.message || 'Map goal could not be queued.'); }
      finally { goalBusy = false; }
    }
    $("cancel-goal").addEventListener('click', () => command({cancel:true}, 'map goal cancellation'));
    canvas.addEventListener('pointerenter', () => { over = true; if (!held && camera) held = {...camera}; });
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0 || !camera) return;
      e.preventDefault(); canvas.focus({preventScroll:true}); held = {...camera};
      drag = {id:e.pointerId, x:e.clientX, y:e.clientY, camera:{...camera}, moved:false};
      try { canvas.setPointerCapture?.(e.pointerId); } catch {} hover(e);
    });
    canvas.addEventListener('pointermove', e => {
      if (drag && drag.id === e.pointerId) {
        const dx = e.clientX-drag.x, dy = e.clientY-drag.y;
        if (Math.hypot(dx,dy)>4) drag.moved = true;
        if (drag.moved) { manual = true; held = panView(drag.camera,size,dx,dy); render(); }
      }
      hover(e);
    });
    canvas.addEventListener('pointerup', e => {
      if (!drag || drag.id !== e.pointerId) return;
      const clicked = !drag.moved; drag = null;
      if (canvas.hasPointerCapture?.(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      if (clicked) {
        const m = hit(e).best;
        if (m && ['bonus','item'].includes(m.kind) && !m.taken) {
          if (!frame?.goal_round || !frame?.goal_capabilities?.includes(m.kind) || !frame.live)
            goalMessage('This session is not ready for map commands.');
          else command({round:frame.goal_round,stage:frame.stage,kind:m.kind,id:m.id,seq:frame.seq}, m.tip);
        }
      }
    });
    const endDrag = () => { drag = null; tip.hidden = true; if (!over && !manual) held = null; };
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('lostpointercapture', endDrag);
    canvas.addEventListener('pointerleave', () => { over = false; tip.hidden = true; if (!drag && !manual) { held = null; render(); } });
    canvas.addEventListener('wheel', e => {
      if (!camera || !Number.isFinite(e.deltaY) || !e.deltaY) return;
      e.preventDefault(); const r = canvas.getBoundingClientRect();
      const delta = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? size.h : 1);
      held = zoomView(camera,size,e.clientX-r.left,e.clientY-r.top,Math.exp(Math.max(-.7,Math.min(.7,delta*.002))),frame?.units);
      manual = true; render();
    }, {passive:false});
    sect.addEventListener("toggle", () => { if (sect.open) { feed.poke(); render(); } });
    const onVis = () => { if (doc.visibilityState !== "hidden") feed.poke(); };
    doc.addEventListener("visibilitychange", onVis);
    const ro = root.ResizeObserver ? new root.ResizeObserver(() => { if (fit()) render(); }) : null;
    ro && ro.observe(stageEl);
    function stop() {
      stopped = true; feed.stop(); ro && ro.disconnect(); doc.removeEventListener("visibilitychange", onVis);
      if (current === ctl) current = null;
    }
    const ctl = { stop, render, get frame() { return frame; }, get view() { return camera && {...camera}; } };
    current = ctl;
    return ctl;
  }
  function detach() { if (current) current.stop(); current = null; }

  // A report image of the same observed frame and map geometry; no browser or new RAM reads.
  function renderSVG({ frame: f, stage: st = null, width = 960, height = 720 } = {}) {
    const validPos = p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite);
    if (!f || f.v !== 1 || !Object.hasOwn(PER_M, f.units) || !validPos(f.player?.pos) || !Number.isFinite(f.t)
        || !Number.isInteger(width) || width < 640 || width > 1920
        || !Number.isInteger(height) || height < 480 || height > 1080) throw Error('Invalid tactical report frame or size');
    for (const rows of [f.enemies || [], f.bonuses || []]) {
      if (!Array.isArray(rows) || rows.length > 512 || rows.some(r => !validPos(r.pos))) throw Error('Invalid tactical actors');
    }
    const plan = f.plan || {};
    if ((plan.route || []).length > 64 || (plan.route || []).some(p => !validPos(p))) throw Error('Invalid route');
    for (const entry of [plan.target, plan.stand, plan.nearest_bonus]) {
      if (entry?.pos && !validPos(entry.pos)) throw Error('Invalid plan position');
    }
    if (st) {
      if (st.kind !== 'mesh' || st.key !== f.stage || st.units !== f.units || !Array.isArray(st.points)
          || st.points.length > 90000 || st.points.length % 3 || !st.points.every(Number.isFinite)) throw Error('Invalid or mismatched stage');
      for (const [key, stride] of [['tris', 3], ['walls', 2], ['cross', 2]]) {
        const ids = st[key] || [];
        if (!Array.isArray(ids) || ids.length > 180000 || ids.length % stride
            || ids.some(n => !Number.isInteger(n) || n < 0 || n >= st.points.length / 3)) throw Error('Invalid stage indices');
      }
      if (st.bounds && (st.bounds.length !== 4 || !st.bounds.every(Number.isFinite))) throw Error('Invalid stage bounds');
      if ((st.climbs || []).length > 2048 || (st.climbs || []).some(c => c.length < 4 || !c.every(Number.isFinite))) throw Error('Invalid climbs');
    }
    const parts = [], stack = [];
    const n = value => { if (!Number.isFinite(value)) throw Error('Non-finite map geometry'); return Number(value.toFixed(2)); };
    const ctx = {
      fillStyle: '#fff', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, font: '11px sans-serif', dash: [], path: '',
      save() { stack.push({ fillStyle: this.fillStyle, strokeStyle: this.strokeStyle, lineWidth: this.lineWidth,
        globalAlpha: this.globalAlpha, font: this.font, dash: this.dash.slice() }); },
      restore() { Object.assign(this, stack.pop()); },
      beginPath() { this.path = ''; }, closePath() { this.path += 'Z '; },
      moveTo(x, y) { this.path += `M${n(x)} ${n(y)} `; }, lineTo(x, y) { this.path += `L${n(x)} ${n(y)} `; },
      arc(x, y, r, a, b) {
        if (!(r >= 0) || Math.abs(b - a - 2 * Math.PI) > .001) throw Error('Unsupported map arc');
        this.path += `M${n(x+r)} ${n(y)} A${n(r)} ${n(r)} 0 1 0 ${n(x-r)} ${n(y)} A${n(r)} ${n(r)} 0 1 0 ${n(x+r)} ${n(y)} `;
      },
      setLineDash(dash) { this.dash = dash; },
      paint(fill) { parts.push(`<path d="${this.path}" fill="${fill ? ESC(this.fillStyle) : 'none'}" `
        + `stroke="${fill ? 'none' : ESC(this.strokeStyle)}" stroke-width="${n(this.lineWidth)}" `
        + `stroke-dasharray="${this.dash.map(n).join(' ')}" opacity="${n(this.globalAlpha)}"/>`); },
      fill() { this.paint(true); }, stroke() { this.paint(false); },
      fillRect(x, y, w, h) { parts.push(`<rect x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" fill="${ESC(this.fillStyle)}"/>`); },
      measureText(text) { return { width: String(text).length * 6.5 }; },
      text(text, x, y, stroke) { parts.push(`<text x="${n(x)}" y="${n(y)}" dominant-baseline="middle" font-family="sans-serif" font-size="11" `
        + `fill="${stroke ? 'none' : ESC(this.fillStyle)}" stroke="${stroke ? ESC(this.strokeStyle) : 'none'}" `
        + `stroke-width="${n(this.lineWidth)}">${ESC(text)}</text>`); },
      strokeText(text, x, y) { this.text(text, x, y, true); }, fillText(text, x, y) { this.text(text, x, y, false); },
    };
    const mapWidth = width - 300, mapHeight = height - 100, mapSide = Math.min(mapWidth, mapHeight);
    const mapX = (mapWidth - mapSide) / 2, mapY = 80 + (mapHeight - mapSide) / 2;
    const view = viewOf({ cx: f.player.pos[0], cz: f.player.pos[2], radius: 20 * perM(f.units), rot: 0 },
      { w: mapSide, h: mapSide });
    const rendered = draw(ctx, { frame: f, stage: st, view, theme: THEME_LIGHT });
    const h = hud({ ...f, seq: f.seq ?? 0 }), time = new Date(f.t * 1000).toISOString();
    const text = (s, x, y, size = 12) => `<text x="${x}" y="${y}" font-family="sans-serif" font-size="${size}" fill="#20232c">${ESC(s)}</text>`;
    const nearby = (f.enemies || []).map(e => ({ e, d: Math.hypot(...e.pos.map((x, i) => x - f.player.pos[i])) }))
      .sort((a, b) => a.d - b.d).slice(0, Math.min(12, Math.floor((height - 180) / 40)));
    const sidebar = nearby.map(({ e, d }, i) => text(`Enemy ${e.id ?? '?'}: ${e.hp ?? '?'} HP · ${metres(d, f.units)}`, mapWidth + 14, 126 + i * 40)
      + text(({ clear: 'Clear shot measured', blocked: 'Cover measured', unknown: 'Shot path untested' })[e.visibility] || 'Shot path untested', mapWidth + 14, 142 + i * 40, 11)).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`
      + `<title>Report moment tactical map</title><desc>${ESC(rendered.map(m => m.tip).filter(Boolean).join('\n'))}</desc>`
      + `<rect width="100%" height="100%" fill="#fafbfc"/>${text('Report moment · observed RAM map', 16, 25, 18)}`
      + text(`${time} · frame ${f.seq ?? '?'} · ${f.title || ''}`, 16, 46)
      + text(`${h.clock} remaining · ${h.score} · ${h.phase}`, 16, 65)
      + `<defs><clipPath id="map"><rect width="${mapSide}" height="${mapSide}"/></clipPath></defs>`
      + `<g transform="translate(${mapX} ${mapY})" clip-path="url(#map)">${parts.join('')}</g>`
      + text('Nearest observed enemies', mapWidth + 14, 100, 14) + sidebar
      + text('Blue: player · Red: enemies · Gold: bonuses · Green: route', 16, height - 8, 11)
      + text(st ? 'Solid: mesh boundary; dashed: crossing' : 'Stage geometry unavailable', mapWidth + 14, height - 28, 10)
      + '</svg>';
    if (svg.length > 4 * 1024 * 1024) throw Error('Tactical report exceeds output limit');
    return svg;
  }

  const api = { html, mount, detach, create, hud, want, viewOf, project, unproject, panView, zoomView, screenDir, marks, draw, phaseLabel, clockText,
    kindColor, kindsHtml,
                metres, themeOf, renderSVG, VIEW, _stages: stages };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GBoxTacticalMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
