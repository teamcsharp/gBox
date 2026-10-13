// Retarget editor maths (gbox/retarget_profile.py mirrored for the live preview): the profile, the per-role
// transforms in target space, the drag handles ("circles" on the joints) and the role assignment ("what is what").
// Pure functions, no DOM: node tests drive them (tests/test_retarget_handles.cjs), retarget-editor.js draws them.
(function (root) {
  "use strict";
  const ROLES = ["hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
    "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"];
  const TORSO = new Set(["hip", "chest", "neck", "l_clav", "r_clav"]);
  const ARMS = new Set(["l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand"]);
  const LEGS = new Set(["l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]);
  const CHILD = { hip: "chest", chest: "neck", neck: "head", l_clav: "l_upper", r_clav: "r_upper", l_upper: "l_fore",
    l_fore: "l_hand", r_upper: "r_fore", r_fore: "r_hand", l_thigh: "l_shin", l_shin: "l_foot", r_thigh: "r_shin",
    r_shin: "r_foot" };
  const PARENT = Object.fromEntries(Object.entries(CHILD).map(([p, c]) => [c, p]));
  const ROOT = r => (ARMS.has(r) ? (r[0] === "l" ? "l_upper" : "r_upper") : LEGS.has(r) ? (r[0] === "l" ? "l_thigh" : "r_thigh") : r);
  const REQUIRED = ["hip", "head"];
  const LABELS = { hip: "Hips", chest: "Chest", neck: "Neck", head: "Head", l_clav: "Left collarbone", r_clav: "Right collarbone",
    l_upper: "Left upper arm", l_fore: "Left forearm", l_hand: "Left hand", r_upper: "Right upper arm", r_fore: "Right forearm",
    r_hand: "Right hand", l_thigh: "Left thigh", l_shin: "Left shin", l_foot: "Left foot", r_thigh: "Right thigh",
    r_shin: "Right shin", r_foot: "Right foot" };
  const RANGE = [0.25, 4];
  const DEFAULT = { roles: {}, height: 1, ground: 0, head: 1, torso_width: 1, arm_length: 1, leg_length: 1, adjust: {} };
  const ADJ = { length: 1, girth: 1, scale: [1, 1, 1], offset: [0, 0, 0], rotate: [0, 0, 0] };

  const num = (v, d, lo, hi) => { const f = Number(v); return Number.isFinite(f) ? Math.min(hi, Math.max(lo, f)) : d; };
  const vec = (v, d, lo, hi) => (Array.isArray(v) && v.length === 3 ? v.map((x, i) => num(x, d[i], lo, hi)) : d.slice());
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  function normalize(p) {
    p = p || {};
    const out = JSON.parse(JSON.stringify(DEFAULT));
    for (const [r, b] of Object.entries(p.roles || {})) if (ROLES.includes(r)) out.roles[r] = String(b || "").trim().slice(0, 128);
    out.height = num(p.height, 1, ...RANGE); out.ground = num(p.ground, 0, -0.5, 0.5); out.head = num(p.head, 1, ...RANGE);
    out.torso_width = num(p.torso_width, 1, ...RANGE); out.arm_length = num(p.arm_length, 1, ...RANGE);
    out.leg_length = num(p.leg_length, 1, ...RANGE);
    for (const [r, a0] of Object.entries(p.adjust || {})) {
      if (!ROLES.includes(r)) continue;
      const a = a0 || {};
      const c = { length: num(a.length, 1, ...RANGE), girth: num(a.girth, 1, ...RANGE), scale: vec(a.scale, [1, 1, 1], ...RANGE),
        offset: vec(a.offset, [0, 0, 0], -1, 1), rotate: vec(a.rotate, [0, 0, 0], -180, 180) };
      if (!same(c, ADJ)) out.adjust[r] = c;
    }
    return out;
  }
  function isIdentity(p) {
    const n = normalize(p);
    return !Object.keys(n.adjust).length && ["height", "ground", "head", "torso_width", "arm_length", "leg_length"].every(k => n[k] === DEFAULT[k]);
  }
  function adjustOf(p, role) { return Object.assign(JSON.parse(JSON.stringify(ADJ)), (p.adjust || {})[role] || {}); }
  function setAdjust(p, role, patch) {                       // a new profile with one role's adjustment changed
    const n = normalize(p), a = Object.assign(adjustOf(n, role), patch);
    n.adjust[role] = a;
    return normalize(n);
  }

  // ---- 3x3 maths (row-major arrays) ----------------------------------------------------
  const I3 = () => [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const mul = (A, B) => A.map((r, i) => [0, 1, 2].map(j => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
  const mv = (A, v) => A.map(r => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
  const add = (a, b) => a.map((x, i) => x + b[i]), sub = (a, b) => a.map((x, i) => x - b[i]), sc = (a, k) => a.map(x => x * k);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], norm = a => Math.sqrt(dot(a, a));
  const diag = d => [[d[0], 0, 0], [0, d[1], 0], [0, 0, d[2]]];
  function euler(deg) {
    const [x, y, z] = deg.map(a => a * Math.PI / 180), [cx, sx, cy, sy, cz, sz] = [Math.cos(x), Math.sin(x), Math.cos(y), Math.sin(y), Math.cos(z), Math.sin(z)];
    return mul(mul([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]), [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]);
  }
  function axis(role, pos) {
    const p = pos[role];
    let d = pos[CHILD[role]] ? sub(pos[CHILD[role]], p) : pos[PARENT[role]] ? sub(p, pos[PARENT[role]]) : [0, 1, 0];
    const n = norm(d);
    return n > 1e-9 ? sc(d, 1 / n) : [0, 1, 0];
  }
  function frame(rolePos, ground) {
    const pts = Object.values(rolePos);
    const centre = rolePos.hip || (pts.length ? sc(pts.reduce(add, [0, 0, 0]), 1 / pts.length) : [0, 0, 0]);
    const g = ground != null ? ground : Math.min(...pts.map(p => p[1]), 0);
    const top = rolePos.head ? rolePos.head[1] : Math.max(...pts.map(p => p[1]));
    return { centre, ground: g, H: Math.max(top - g, 1e-6) };
  }

  // {role: {A, t}} (x' = A x + t) and the transform of joints without a role; same order as role_transforms()
  function roleTransforms(rolePos, profile, ground) {
    const p = normalize(profile), pos = {};
    for (const [r, v] of Object.entries(rolePos || {})) if (ROLES.includes(r)) pos[r] = v.slice();
    const f = frame(pos, ground), c = f.centre, H = f.H, k = p.height;
    const gpt = [c[0], f.ground, c[2]];
    const G = diag([k, k, k]), gt = add(sub(gpt, sc(gpt, k)), [0, p.ground * H, 0]);
    const tw = p.torso_width, Wx = diag([tw, 1, 1]), wt = [c[0] - tw * c[0], 0, 0];
    const compose = (A, t) => ({ A: mul(G, A), t: add(mv(G, t), gt) });
    const out = {};
    for (const [role, pv] of Object.entries(pos)) {
      const a = adjustOf(p, role);
      const len = a.length * (ARMS.has(role) ? p.arm_length : LEGS.has(role) ? p.leg_length : 1), g = a.girth;
      const d = axis(role, pos);
      const L = [0, 1, 2].map(i => [0, 1, 2].map(j => (i === j ? g : 0) + (len - g) * d[i] * d[j]));
      let S = diag(a.scale);
      if (role === "head") S = S.map(r => r.map(x => x * p.head));
      let M = mul(mul(euler(a.rotate), L), S);
      let t = add(sub(pv, mv(M, pv)), sc(a.offset, H));
      if (TORSO.has(role)) { t = add(mv(Wx, t), wt); M = mul(Wx, M); }
      else { const rt = pos[ROOT(role)] || pv; t = add(t, [(tw - 1) * (rt[0] - c[0]), 0, 0]); }
      out[role] = compose(M, t);
    }
    return { roles: out, other: compose(Wx, wt), frame: f };
  }
  // one vertex: influences [[role|null, weight], ...]
  function applyVertex(v, influences, tr) {
    let o = [0, 0, 0], tot = 0;
    for (const [role, w] of influences) {
      if (!(w > 0)) continue;
      const T = (role && tr.roles[role]) || tr.other;
      o = add(o, sc(add(mv(T.A, v), T.t), w)); tot += w;
    }
    return tot > 0 ? sc(o, 1 / tot) : v.slice();
  }
  // a whole mesh: positions (flat xyz), roleIdx/weights (flat, k per vertex; role index into ROLES or -1)
  function applyPositions(positions, roleIdx, weights, k, tr, out) {
    const n = positions.length / 3, res = out || new Float32Array(positions.length);
    const As = ROLES.map(r => tr.roles[r] || tr.other);
    for (let i = 0; i < n; i++) {
      const x = positions[3 * i], y = positions[3 * i + 1], z = positions[3 * i + 2];
      let ox = 0, oy = 0, oz = 0, tot = 0;
      for (let j = 0; j < k; j++) {
        const w = weights[i * k + j]; if (!(w > 0)) continue;
        const ri = roleIdx[i * k + j], T = ri >= 0 ? As[ri] : tr.other, A = T.A;
        ox += w * (A[0][0] * x + A[0][1] * y + A[0][2] * z + T.t[0]);
        oy += w * (A[1][0] * x + A[1][1] * y + A[1][2] * z + T.t[1]);
        oz += w * (A[2][0] * x + A[2][1] * y + A[2][2] * z + T.t[2]);
        tot += w;
      }
      if (tot > 0) { res[3 * i] = ox / tot; res[3 * i + 1] = oy / tot; res[3 * i + 2] = oz / tot; }
      else { res[3 * i] = x; res[3 * i + 1] = y; res[3 * i + 2] = z; }
    }
    return res;
  }

  // ---- "what is what": donor bones <-> body roles ---------------------------------------
  const PATTERNS = [
    ["head", /head|kopf|atama|\bhd\b/i], ["neck", /neck|kubi/i], ["chest", /chest|spine2|spine1|upper.?body|torso|ribs?|mune/i],
    ["hip", /hips?$|pelvis|root.?hip|^hip|koshi|waist/i],
    ["l_clav", /(l(eft)?[_ .-]?(clav|collar|shoulder))|((clav|collar|shoulder).*[_ .-]l(eft)?$)/i],
    ["r_clav", /(r(ight)?[_ .-]?(clav|collar|shoulder))|((clav|collar|shoulder).*[_ .-]r(ight)?$)/i],
    ["l_fore", /(l(eft)?[_ .-]?(fore.?arm|lower.?arm|elbow))|((fore.?arm|lower.?arm|elbow).*[_ .-]l(eft)?$)/i],
    ["r_fore", /(r(ight)?[_ .-]?(fore.?arm|lower.?arm|elbow))|((fore.?arm|lower.?arm|elbow).*[_ .-]r(ight)?$)/i],
    ["l_upper", /(l(eft)?[_ .-]?(upper.?arm|arm))|((upper.?arm|arm).*[_ .-]l(eft)?$)/i],
    ["r_upper", /(r(ight)?[_ .-]?(upper.?arm|arm))|((upper.?arm|arm).*[_ .-]r(ight)?$)/i],
    ["l_hand", /(l(eft)?[_ .-]?(hand|wrist))|((hand|wrist).*[_ .-]l(eft)?$)/i],
    ["r_hand", /(r(ight)?[_ .-]?(hand|wrist))|((hand|wrist).*[_ .-]r(ight)?$)/i],
    ["l_shin", /(l(eft)?[_ .-]?(shin|calf|knee|lower.?leg))|((shin|calf|knee|lower.?leg).*[_ .-]l(eft)?$)/i],
    ["r_shin", /(r(ight)?[_ .-]?(shin|calf|knee|lower.?leg))|((shin|calf|knee|lower.?leg).*[_ .-]r(ight)?$)/i],
    ["l_thigh", /(l(eft)?[_ .-]?(thigh|upper.?leg|up.?leg|leg))|((thigh|upper.?leg|up.?leg|leg).*[_ .-]l(eft)?$)/i],
    ["r_thigh", /(r(ight)?[_ .-]?(thigh|upper.?leg|up.?leg|leg))|((thigh|upper.?leg|up.?leg|leg).*[_ .-]r(ight)?$)/i],
    ["l_foot", /(l(eft)?[_ .-]?(foot|ankle))|((foot|ankle).*[_ .-]l(eft)?$)/i],
    ["r_foot", /(r(ight)?[_ .-]?(foot|ankle))|((foot|ankle).*[_ .-]r(ight)?$)/i],
  ];
  // name-based guesses for bones the collection has no role for (Bip01 L Forearm, mixamorig:LeftArm, ...)
  function guessRoles(boneNames, have = {}) {
    const out = Object.assign({}, have), used = new Set(Object.values(out));
    for (const [role, rx] of PATTERNS) {
      if (out[role]) continue;
      const hit = boneNames.find(b => !used.has(b) && rx.test(String(b).replace(/^mixamorig:|^bip0?1[ _]?/i, "")));
      if (hit) { out[role] = hit; used.add(hit); }
    }
    return out;
  }
  // a bone holds one role: assigning it elsewhere moves it; bone "" unassigns the role
  function assign(roles, role, bone) {
    if (!ROLES.includes(role)) throw new Error("unknown role " + role);
    const out = {};
    for (const [r, b] of Object.entries(roles || {})) if (r !== role && b && b !== bone) out[r] = b;
    if (bone) out[role] = bone;
    return out;
  }
  function issues(roles) {
    const miss = REQUIRED.filter(r => !(roles || {})[r]);
    const limbs = ["l_upper", "r_upper", "l_thigh", "r_thigh"].filter(r => !(roles || {})[r]);
    return { ok: !miss.length, missing: miss, limbs };
  }
  // the profile's role overrides relative to the collection's own roles ("" = removed)
  function roleOverrides(base, edited) {
    const out = {};
    for (const r of ROLES) {
      const a = (base || {})[r] || "", b = (edited || {})[r] || "";
      if (a !== b) out[r] = b;
    }
    return out;
  }
  function applyOverrides(base, overrides) {
    let out = Object.assign({}, base || {});
    for (const [r, b] of Object.entries(overrides || {})) out = assign(out, r, b);
    return out;
  }
  // each bone's role: its own, else its nearest ancestor's (default hip), like re4gc_enemies._role_of_joint
  function boneRoles(names, parents, roles) {
    const byBone = new Map(Object.entries(roles || {}).map(([r, b]) => [b, r]));
    return names.map((_, i) => {
      for (let k = i, guard = 0; k >= 0 && guard < 512; k = parents[k], guard++) if (byBone.has(names[k])) return byBone.get(names[k]);
      return "hip";
    });
  }

  // ---- the circles: drag handles in the front view (x right, y up) ----------------------
  // handles(rolePos, profile, ground) -> [{id, kind, role, at:[x,y,z], r}] where at is the handle's displayed point
  function handles(rolePos, profile, ground) {
    const p = normalize(profile), f = frame(rolePos, ground), H = f.H, c = f.centre, out = [];
    const tr = roleTransforms(rolePos, p, ground);
    const shown = r => add(mv(tr.roles[r].A, rolePos[r]), tr.roles[r].t);     // a joint where the profile puts it
    for (const r of ["l_upper", "l_fore", "r_upper", "r_fore", "l_thigh", "l_shin", "r_thigh", "r_shin"]) {
      const ch = CHILD[r];
      if (!rolePos[r] || !rolePos[ch]) continue;
      const T = tr.roles[r], at = add(mv(T.A, rolePos[ch]), T.t);    // the bone's end, stretched by its length
      out.push({ id: "len:" + r, kind: "length", role: r, at, r: 0.025 * H });
    }
    if (rolePos.head) {
      const hc = shown("head");
      out.push({ id: "head", kind: "head", role: "head", at: add(hc, [0, 0.12 * H * p.head * adjustOf(p, "head").scale[1] * p.height, 0]), r: 0.03 * H, ring: 0.12 * H * p.head * p.height, centre: hc });
    }
    for (const r of ["l_upper", "r_upper"]) if (rolePos[r]) out.push({ id: "width:" + r, kind: "width", role: r, at: shown(r), r: 0.025 * H });
    const top = (rolePos.head ? rolePos.head[1] : f.ground + H);
    out.push({ id: "height", kind: "height", role: null, at: [c[0], f.ground + p.height * (top - f.ground) + 0.18 * H * p.height + p.ground * H, c[2]], r: 0.03 * H });
    out.push({ id: "ground", kind: "ground", role: null, at: [c[0] + 0.35 * H, f.ground + p.ground * H, c[2]], r: 0.03 * H });
    return out;
  }
  // drag a handle from its point to `to` (model space, the front view's x/y) -> the new profile
  function drag(profile, handle, to, rolePos, ground) {
    const p = normalize(profile), f = frame(rolePos, ground), H = f.H, c = f.centre;
    if (handle.kind === "length") {
      const r = handle.role, ch = CHILD[r], tr = roleTransforms(rolePos, p, ground).roles[r];
      const piv = add(mv(tr.A, rolePos[r]), tr.t), d = sub(rolePos[ch], rolePos[r]);
      const glob = (ARMS.has(r) ? p.arm_length : p.leg_length) * p.height;
      const flat = [to[0] - piv[0], to[1] - piv[1], 0], dd = [d[0], d[1], 0];
      const ratio = dot(flat, dd) / Math.max(dot(dd, dd), 1e-12);            // along the bone, in the front view
      return setAdjust(p, r, { length: num(ratio / glob, 1, ...RANGE) });
    }
    if (handle.kind === "head") {
      const cen = handle.centre || rolePos.head, base = 0.12 * H * p.height;
      p.head = num(norm(sub([to[0], to[1], 0], [cen[0], cen[1], 0])) / Math.max(base, 1e-9) / adjustOf(p, "head").scale[1], 1, ...RANGE);
      return normalize(p);
    }
    if (handle.kind === "width") {
      const sx = rolePos[handle.role][0] - c[0];
      p.torso_width = num(Math.abs((to[0] - c[0]) / p.height) / Math.max(Math.abs(sx), 1e-9), 1, ...RANGE);
      return normalize(p);
    }
    if (handle.kind === "height") {
      const top = (rolePos.head ? rolePos.head[1] : f.ground + H) - f.ground + 0.18 * H;
      p.height = num((to[1] - f.ground - p.ground * H) / Math.max(top, 1e-9), 1, ...RANGE);
      return normalize(p);
    }
    if (handle.kind === "ground") { p.ground = num((to[1] - f.ground) / H, 0, -0.5, 0.5); return normalize(p); }
    if (handle.kind === "offset") {
      const a = adjustOf(p, handle.role), from = handle.from || handle.at;
      return setAdjust(p, handle.role, { offset: add(a.offset, [(to[0] - from[0]) / H, (to[1] - from[1]) / H, 0]) });
    }
    return p;
  }
  // the nearest handle within its radius (screen-tolerant: tol in model units)
  function hit(list, at, tol = 0) {
    let best = null, bd = Infinity;
    for (const h of list) {
      const d = Math.hypot(h.at[0] - at[0], h.at[1] - at[1]);
      if (d <= h.r + tol && d < bd) { best = h; bd = d; }
    }
    return best;
  }
  // front-view mapping between model x/y and canvas pixels (y down)
  function view(bounds, w, h, pad = 0.08) {
    const sx = bounds.max[0] - bounds.min[0], sy = bounds.max[1] - bounds.min[1];
    const s = Math.min(w / Math.max(sx, 1e-6), h / Math.max(sy, 1e-6)) * (1 - 2 * pad);
    const cx = (bounds.min[0] + bounds.max[0]) / 2, cy = (bounds.min[1] + bounds.max[1]) / 2;
    return { s, toScreen: p => [w / 2 + (p[0] - cx) * s, h / 2 - (p[1] - cy) * s],
      toModel: q => [cx + (q[0] - w / 2) / s, cy - (q[1] - h / 2) / s, 0] };
  }
  // base fit for the preview: donor joints -> target space by figure height (head over ground), hips aligned
  function baseFit(donorPos, donorGround, targetPos, targetGround) {
    const fd = frame(donorPos, donorGround), ft = frame(targetPos, targetGround), s = ft.H / fd.H;
    const t = [ft.centre[0] - fd.centre[0] * s, ft.ground - fd.ground * s, ft.centre[2] - fd.centre[2] * s];
    return { s, t, apply: v => [v[0] * s + t[0], v[1] * s + t[1], v[2] * s + t[2]] };
  }
  // a humanoid at the target game's proportions when no stock model of that slot is in the collection
  function standardSkeleton(height = 1.7) {
    const k = height / 1.7, P = { hip: [0, 0.95, 0], chest: [0, 1.25, 0], neck: [0, 1.48, 0], head: [0, 1.58, 0],
      l_clav: [0.06, 1.42, 0], r_clav: [-0.06, 1.42, 0], l_upper: [0.18, 1.42, 0], l_fore: [0.45, 1.42, 0], l_hand: [0.7, 1.42, 0],
      r_upper: [-0.18, 1.42, 0], r_fore: [-0.45, 1.42, 0], r_hand: [-0.7, 1.42, 0], l_thigh: [0.1, 0.9, 0], l_shin: [0.1, 0.5, 0],
      l_foot: [0.1, 0.08, 0], r_thigh: [-0.1, 0.9, 0], r_shin: [-0.1, 0.5, 0], r_foot: [-0.1, 0.08, 0] };
    return Object.fromEntries(Object.entries(P).map(([r, v]) => [r, v.map(x => x * k)]));
  }

  const api = { ROLES, LABELS, REQUIRED, DEFAULT, CHILD, PARENT, normalize, isIdentity, adjustOf, setAdjust, roleTransforms,
    applyVertex, applyPositions, guessRoles, assign, issues, roleOverrides, applyOverrides, boneRoles, handles, drag, hit,
    view, frame, baseFit, standardSkeleton, euler };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxRetargetHandles = api;
})(typeof window !== "undefined" ? window : globalThis);
