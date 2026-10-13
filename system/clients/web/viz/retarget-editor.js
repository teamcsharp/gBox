// Retarget editor (gbox/retarget_profile.py): how one collection character is scaled and proportioned into one game.
// Left: the donor with a circle on every bone - arm a body role in the list, then click the bone that IS that role
// ("what is what"). Right: the target slot's stock model (or a standard skeleton at the game's proportions) with the
// donor fitted over it, live; drag the circles to stretch a limb, size the head, widen the shoulders, raise the
// figure or lift it off the ground (Shift-drag any joint moves that part). Save keeps it on the server per donor,
// game and slot; the next build of that slot (one swap or the whole cast) fits with it.
// Shared by the web shell and the desktop app (../web/viz/retarget-editor.js); the controller renders HTML strings
// so node tests drive it without a DOM (tests/test_retarget_editor.cjs).
(function (root) {
  "use strict";
  const H = typeof module === "object" && module.exports ? require("./retarget-handles.js") : root.GBoxRetargetHandles;
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const GLOBALS = [["height", "Height", 0.5, 2, 0.01], ["ground", "Ground lift", -0.2, 0.2, 0.005], ["head", "Head size", 0.5, 2.5, 0.01],
    ["torso_width", "Torso width", 0.6, 2, 0.01], ["arm_length", "Arm length", 0.5, 2, 0.01], ["leg_length", "Leg length", 0.5, 2, 0.01]];
  const PART = [["length", "Length", 0.25, 3, 0.01], ["girth", "Girth", 0.25, 3, 0.01]];
  const XYZ = [["scale", "Scale", 0.25, 3, 0.01], ["offset", "Move", -0.3, 0.3, 0.005], ["rotate", "Turn", -180, 180, 1]];
  const COLORS = { hip: "#ffd36b", chest: "#ffb46b", neck: "#ff9f6b", head: "#ff6b8b", l_clav: "#9fc2ff", r_clav: "#8fe6a8",
    l_upper: "#6ea8ff", l_fore: "#4f8cff", l_hand: "#3a6fd8", r_upper: "#8fe6a8", r_fore: "#5fd18a", r_hand: "#3fae6a",
    l_thigh: "#c49bff", l_shin: "#a77bff", l_foot: "#8a5cf0", r_thigh: "#ff9be0", r_shin: "#f07bc8", r_foot: "#d85cae" };

  // ---- HTML (strings) --------------------------------------------------------------------
  function slider(path, label, lo, hi, step, value, unit = "×") {
    const v = Number(value);
    return `<label class="rt-sl" title="${ESC(label)}"><span>${ESC(label)}</span>
      <input type="range" data-rt-set="${ESC(path)}" min="${lo}" max="${hi}" step="${step}" value="${v}">
      <output>${unit === "°" ? v.toFixed(0) + "°" : unit === "%" ? (v * 100).toFixed(1) + "%" : v.toFixed(2) + "×"}</output></label>`;
  }
  function globalsHTML(profile) {
    const p = H.normalize(profile);
    return GLOBALS.map(([k, l, lo, hi, st]) => slider(k, l, lo, hi, st, p[k], k === "ground" ? "%" : "×")).join("");
  }
  function partHTML(profile, role) {
    if (!role) return '<div class="mut rt-hint">Click a role (or a circle) to adjust that part on its own.</div>';
    const a = H.adjustOf(H.normalize(profile), role);
    const xyz = XYZ.map(([k, l, lo, hi, st]) => [0, 1, 2].map(i => slider(`adjust.${role}.${k}.${i}`, `${l} ${"XYZ"[i]}`, lo, hi, st, a[k][i],
      k === "rotate" ? "°" : k === "offset" ? "%" : "×")).join("")).join("");
    return `<div class="rt-part"><b>${ESC(H.LABELS[role] || role)}</b>
      ${PART.map(([k, l, lo, hi, st]) => slider(`adjust.${role}.${k}`, l, lo, hi, st, a[k])).join("")}${xyz}
      <button type="button" class="act" data-rt-go="part-reset" data-role="${ESC(role)}">Reset this part</button></div>`;
  }
  // the role list: each body role, the donor bone that is it (a picker of every bone), where the mapping came from
  function rolesHTML(state) {
    const bones = state.bones || [], is = H.issues(state.roles);
    return H.ROLES.map(role => {
      const bone = (state.roles || {})[role] || "", from = bone ? ((state.baseRoles || {})[role] === bone ? "collection"
        : (state.guessed || {})[role] === bone ? "guessed" : "yours") : (is.missing.includes(role) ? "required" : "");
      const opts = ['<option value="">(none)</option>'].concat(bones.map(b => `<option value="${ESC(b)}"${b === bone ? " selected" : ""}>${ESC(b)}</option>`));
      if (bone && !bones.includes(bone)) opts.push(`<option value="${ESC(bone)}" selected>${ESC(bone)} (not in model)</option>`);
      return `<div class="rt-role${state.armed === role ? " armed" : ""}${state.part === role ? " sel" : ""}${from === "required" ? " miss" : ""}" data-rt-role="${role}">
        <i style="background:${COLORS[role]}"></i><span class="rt-rn" data-rt-part="${role}">${ESC(H.LABELS[role])}</span>
        <select data-rt-bone="${role}">${opts.join("")}</select>
        <button type="button" class="act" data-rt-arm="${role}" title="Then click the bone in the donor view">${state.armed === role ? "…click a bone" : "pick"}</button>
        <em class="rt-from">${ESC(from)}</em></div>`;
    }).join("");
  }
  function headerHTML(state) {
    const slots = state.slots || [];
    const pick = slots.length ? `<select data-rt="slot">${slots.map(s => `<option value="${ESC(s.slot)}"${s.slot === state.slot ? " selected" : ""}>${ESC(s.name || s.slot)}</option>`).join("")}</select>`
      : `<input data-rt="slot" value="${ESC(state.slot || "")}" size="14" placeholder="slot (player)">`;
    return `<b>Retarget ${ESC(state.name || state.slug)} → ${ESC(state.title || state.gid)}</b> ${pick}
      <span class="mut rt-saved">${ESC(state.savedNote || "")}</span>`;
  }
  function frameHTML() {
    return `<div class="rt-h" data-rt-part-slot="header"></div>
      <div class="rt-body">
        <div class="rt-views">
          <div class="rt-view"><div class="rt-cap">Donor · bones <span class="mut">(arm a role, click its bone)</span></div><div class="rt-stage" data-rt-stage="donor"></div></div>
          <div class="rt-view"><div class="rt-cap">In the game · <span data-rt="target-name">target</span> <span class="mut">(drag the circles; Shift-drag moves a part)</span></div><div class="rt-stage" data-rt-stage="target"></div></div>
        </div>
        <div class="rt-side scroll">
          <div class="rt-sec"><b>Proportions</b><div data-rt-part-slot="globals"></div></div>
          <div class="rt-sec" data-rt-part-slot="part"></div>
          <div class="rt-sec"><b>What is what</b> <button type="button" class="act" data-rt-go="guess" title="Fill empty roles from bone names">Guess from names</button><div data-rt-part-slot="roles"></div></div>
        </div>
      </div>
      <div class="rt-f"><span data-rt="status" class="mut"></span>
        <button type="button" class="act" data-rt-go="reset">Reset</button>
        <button type="button" class="act" data-rt-go="save-all" title="Every slot of this game without its own profile">Save for the whole game</button>
        <button type="button" class="act pri" data-rt-go="save">Save for this slot</button>
        <button type="button" class="act" data-rt-go="close">Close</button></div>`;
  }

  // ---- the controller (no DOM) ------------------------------------------------------------
  // io: api(path, body?) -> data (throws), render(part, html), status(text), onChange(state)
  function controller(io, opts) {
    const st = { slug: opts.slug, name: opts.name || "", gid: opts.gid, title: opts.title || "", slot: opts.slot || "player",
      slots: [], view: null, reference: null, baseRoles: {}, roles: {}, guessed: {}, profile: H.normalize({}), bones: [],
      armed: null, part: null, dirty: false, savedNote: "" };
    const q = () => `game_id=${encodeURIComponent(st.gid)}&slot=${encodeURIComponent(st.slot)}`;
    const changed = () => { io.onChange && io.onChange(st); };
    function renderAll() {
      io.render("header", headerHTML(st)); io.render("globals", globalsHTML(st.profile));
      io.render("part", partHTML(st.profile, st.part)); io.render("roles", rolesHTML(st));
    }
    async function load() {
      io.status("Loading the profile…");
      const [v, ref, src, game] = await Promise.all([
        io.api(`/api/characters/${encodeURIComponent(st.slug)}/retarget_profile?${q()}`),
        io.api(`/api/retarget/reference?${q()}`).catch(() => null),
        st.slots.length ? Promise.resolve(null) : io.api(`/api/cast_swap/sources?game_id=${encodeURIComponent(st.gid)}`).catch(() => null),
        st.title ? Promise.resolve(null) : io.api(`/api/catalog/${encodeURIComponent(st.gid)}`).catch(() => null)]);
      st.view = v; st.name = v.name || st.name; st.reference = ref && ref.reference;
      if (game && game.title) st.title = game.title;
      if (src && Array.isArray(src.slots) && src.slots.length) {
        st.slots = src.slots.map(s => ({ slot: s.slot, name: s.name }));
        if (!st.slots.some(s => s.slot === st.slot)) st.slots.unshift({ slot: st.slot, name: st.slot });
      }
      st.baseRoles = Object.assign({}, v.rig_roles || {});
      const p = H.normalize(v.resolved || {});
      st.roles = H.applyOverrides(st.baseRoles, p.roles); st.profile = p; st.dirty = false;
      st.savedNote = v.profile ? "saved for this slot" : v.game_wide ? "using the game-wide profile" : "automatic fit (nothing saved)";
      renderAll();
      io.status(H.issues(st.roles).ok ? "Drag the circles on the right; the fit updates live." : `Assign ${H.issues(st.roles).missing.join(" and ")} first: the fit needs them.`);
      changed();
      return st;
    }
    function setBones(names) {                                // the donor model's bone names, once it has loaded
      st.bones = names.slice();
      st.guessed = H.guessRoles(st.bones, {});
      renderAll(); changed();
    }
    function guess() {
      const before = Object.keys(st.roles).length;
      st.roles = H.guessRoles(st.bones, st.roles); st.dirty = true;
      io.status(`${Object.keys(st.roles).length - before} roles filled from bone names`);
      renderAll(); changed();
    }
    function arm(role) { st.armed = st.armed === role ? null : role; st.part = role; renderAll(); }
    function setRoleBone(role, bone) {
      st.roles = H.assign(st.roles, role, bone); st.dirty = true; st.armed = null;
      io.render("roles", rolesHTML(st)); changed();
    }
    function clickBone(bone) {                                // a bone dot clicked in the donor view
      if (!st.armed) { const r = Object.entries(st.roles).find(([, b]) => b === bone); if (r) selectPart(r[0]); return null; }
      const role = st.armed; setRoleBone(role, bone); io.status(`${H.LABELS[role]} = ${bone}`); return role;
    }
    function selectPart(role) { st.part = role; io.render("part", partHTML(st.profile, role)); io.render("roles", rolesHTML(st)); }
    function setValue(path, value) {                          // "height" | "adjust.l_fore.length" | "adjust.head.offset.1"
      const parts = path.split("."), v = Number(value);
      if (parts[0] === "adjust") {
        const [, role, key, i] = parts, a = H.adjustOf(st.profile, role);
        if (i !== undefined) { a[key] = a[key].slice(); a[key][+i] = v; } else a[key] = v;
        st.profile = H.setAdjust(st.profile, role, { [key]: a[key] });
      } else st.profile = H.normalize(Object.assign({}, st.profile, { [parts[0]]: v }));
      st.dirty = true; changed();
    }
    function resetPart(role) {
      const p = H.normalize(st.profile); delete p.adjust[role]; st.profile = p; st.dirty = true;
      io.render("part", partHTML(st.profile, role)); changed();
    }
    function dragTo(handle, to, pivots, ground) {             // a circle dragged in the target view
      st.profile = H.drag(st.profile, handle, to, pivots, ground); st.dirty = true;
      if (handle.role && handle.kind !== "width") st.part = handle.role;
      changed();
    }
    function settle() { io.render("globals", globalsHTML(st.profile)); io.render("part", partHTML(st.profile, st.part)); }
    function payload(scope) {
      const prof = H.normalize(st.profile);
      prof.roles = H.roleOverrides(st.baseRoles, st.roles);
      return { game_id: st.gid, slot: scope === "game" ? "" : st.slot, profile: prof };
    }
    async function save(scope = "slot") {
      const is = H.issues(st.roles);
      if (!is.ok) { io.status(`Not saved: ${is.missing.join(" and ")} must be assigned`); return null; }
      io.status("Saving…");
      const v = await io.api(`/api/characters/${encodeURIComponent(st.slug)}/retarget_profile`, payload(scope));
      st.view = v; st.dirty = false;
      st.savedNote = scope === "game" ? "saved for the whole game" : "saved for this slot";
      io.render("header", headerHTML(st));
      io.status(`✓ Saved. The next build of ${scope === "game" ? "this game" : st.slot} fits ${st.name || st.slug} with it (marked for rebuild).`);
      return v;
    }
    async function reset(scope = "slot") {
      await io.api(`/api/characters/${encodeURIComponent(st.slug)}/retarget_profile`,
        { game_id: st.gid, slot: scope === "game" ? "" : st.slot, reset: true });
      return load();
    }
    async function setSlot(slot) { st.slot = slot || "player"; return load(); }
    return { state: st, load, setBones, guess, arm, setRoleBone, clickBone, selectPart, setValue, resetPart, dragTo, settle,
      payload, save, reset, setSlot, renderAll };
  }

  // ---- the browser: dialog + two three.js views + circles -----------------------------------
  const CSS = `#rtedit{position:fixed;left:50%;top:5vh;transform:translateX(-50%);z-index:98;width:min(1040px,calc(100vw - 24px));
    height:min(680px,calc(100vh - 10vh));display:flex;flex-direction:column;box-sizing:border-box;background:var(--bg,#101318);
    color:var(--fg,#dfe4ec);border:1px solid var(--line,#2c3340);border-radius:10px;box-shadow:0 12px 40px #000c;font-size:12.5px}
    #rtedit .rt-h{display:flex;gap:8px;align-items:center;padding:7px 10px;border-bottom:1px solid var(--line,#2c3340);cursor:move;flex-wrap:wrap}
    #rtedit .rt-body{flex:1;min-height:0;display:flex}#rtedit .rt-views{flex:1;min-width:0;display:flex;gap:6px;padding:6px}
    #rtedit .rt-view{flex:1;min-width:0;display:flex;flex-direction:column}#rtedit .rt-cap{font-size:11px;padding:2px 2px 4px}
    #rtedit .rt-stage{flex:1;position:relative;background:#0b0d12;border-radius:6px;overflow:hidden;min-height:200px}
    #rtedit .rt-stage canvas{position:absolute;inset:0;width:100%;height:100%}#rtedit .rt-stage canvas.ov{cursor:crosshair}
    #rtedit .rt-side{width:330px;overflow:auto;border-left:1px solid var(--line,#2c3340);padding:6px 8px}
    #rtedit .rt-sec{margin-bottom:10px}#rtedit .rt-sl{display:grid;grid-template-columns:92px 1fr 52px;gap:4px;align-items:center;font-size:11px}
    #rtedit .rt-sl input{width:100%;accent-color:var(--acc,#4f8cff)}#rtedit .rt-sl output{text-align:right;font-variant-numeric:tabular-nums}
    #rtedit .rt-role{display:grid;grid-template-columns:10px 96px 1fr 44px 52px;gap:4px;align-items:center;padding:1px 2px;border-radius:4px}
    #rtedit .rt-role i{width:9px;height:9px;border-radius:50%}#rtedit .rt-role select{min-width:0;font-size:11px}
    #rtedit .rt-role .rt-rn{cursor:pointer;font-size:11.5px}#rtedit .rt-role.sel{background:#ffffff10}#rtedit .rt-role.armed{outline:1px solid #ffb46b}
    #rtedit .rt-role.miss .rt-rn,#rtedit .rt-role.miss em{color:#ff8b8b}#rtedit .rt-role em{font-size:10px;color:#7d8696}
    #rtedit .rt-role button{font-size:10.5px;padding:1px 4px}#rtedit .rt-f{display:flex;gap:6px;align-items:center;padding:6px 10px;border-top:1px solid var(--line,#2c3340)}
    #rtedit .rt-f [data-rt=status]{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #rtedit .rt-part b{display:block;margin:2px 0}#rtedit .rt-hint{font-size:11px}`;

  async function loadThree(io) {
    if (io.loadModules) return io.loadModules();
    return { THREE: await import("https://cdn.jsdelivr.net/npm/three@0.160.0/+esm"),
      GLTFLoader: (await import("https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm")).GLTFLoader };
  }
  // a loaded glTF -> {bones: [{name, parent, pos}], meshes: [{pos Float32Array, index, boneOf[], skinIdx, skinW}], ground}
  function readModel(THREE, gltf) {
    gltf.scene.updateMatrixWorld(true);
    const bones = [], byObj = new Map();
    gltf.scene.traverse(o => { if (o.isBone) { byObj.set(o, bones.length); bones.push({ obj: o, name: o.name || `bone${bones.length}` }); } });
    for (const b of bones) { let p = b.obj.parent; while (p && !byObj.has(p)) p = p.parent; b.parent = p ? byObj.get(p) : -1;
      b.pos = b.obj.getWorldPosition(new THREE.Vector3()).toArray(); }
    const meshes = [], v = new THREE.Vector3();
    gltf.scene.traverse(o => {
      if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
      const g = o.geometry, n = g.attributes.position.count, pos = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        v.fromBufferAttribute(g.attributes.position, i);
        if (o.isSkinnedMesh && o.applyBoneTransform) o.applyBoneTransform(i, v);
        v.applyMatrix4(o.matrixWorld); pos[3 * i] = v.x; pos[3 * i + 1] = v.y; pos[3 * i + 2] = v.z;
      }
      let owner = o.parent; while (owner && !byObj.has(owner)) owner = owner.parent;
      const skinBones = o.isSkinnedMesh && o.skeleton ? o.skeleton.bones.map(b => byObj.has(b) ? byObj.get(b) : -1) : null;
      meshes.push({ pos, index: g.index ? g.index.array : null, skinBones, owner: owner ? byObj.get(owner) : -1,
        skinIdx: skinBones && g.attributes.skinIndex ? g.attributes.skinIndex.array : null,
        skinW: skinBones && g.attributes.skinWeight ? g.attributes.skinWeight.array : null });
    });
    let ground = Infinity; for (const m of meshes) for (let i = 1; i < m.pos.length; i += 3) ground = Math.min(ground, m.pos[i]);
    return { bones, meshes, ground: Number.isFinite(ground) ? ground : 0 };
  }

  function open(doc, io, opts) {
    doc.getElementById("rtedit")?.remove();
    if (!doc.getElementById("rtedit-css")) { const s = doc.createElement("style"); s.id = "rtedit-css"; s.textContent = CSS; doc.head.append(s); }
    const el = doc.createElement("div");
    el.id = "rtedit"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Retarget editor");
    el.innerHTML = frameHTML(); doc.body.append(el);
    if (io.drag) io.drag(el);                               // dragAnywhere: the canvases keep their own pointer work
    const q = s => el.querySelector(s);
    let dead = false;
    const views = { donor: null, target: null };
    const ui = Object.assign({}, io, {
      render: (part, html) => { const p = q(`[data-rt-part-slot="${part}"]`); if (p) p.innerHTML = html; },
      status: t => { const s = q('[data-rt="status"]'); if (s) s.textContent = t; },
      onChange: () => schedule(),
    });
    const c = controller(ui, opts);
    let raf = 0;
    function schedule() { if (!raf && !dead) raf = requestAnimationFrame(() => { raf = 0; redraw(); }); }

    // ---- scene data (filled once the models load) ----
    let THREE = null, Loader = null, donor = null, target = null, R = null, donorPos = {}, fit = null, pivots = {}, tPos = {}, tGround = 0;
    let previewMeshes = [], drag = null;
    function rolePositions(model, roles, rot) {
      const out = {};
      for (const [role, bone] of Object.entries(roles || {})) {
        const b = model.bones.find(x => x.name === bone); if (b) out[role] = H.rotate(rot, b.pos);
      }
      return out;
    }
    function refit() {                                        // roles changed: new pivots, new per-vertex roles
      if (!donor) return;
      const raw = rolePositions(donor, c.state.roles, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]);
      R = H.facing(raw);
      donorPos = rolePositions(donor, c.state.roles, R);
      const dGround = Math.min(...donor.meshes.flatMap(m => { const out = []; for (let i = 0; i < m.pos.length; i += 3 * 7) out.push(H.rotate(R, [m.pos[i], m.pos[i + 1], m.pos[i + 2]])[1]); return out; }), Infinity);
      if (!donorPos.hip || !donorPos.head) { fit = null; return; }
      fit = H.baseFit(donorPos, Number.isFinite(dGround) ? dGround : 0, tPos, tGround);
      pivots = Object.fromEntries(Object.entries(donorPos).map(([r, p]) => [r, fit.apply(p)]));
      const names = donor.bones.map(b => b.name), parents = donor.bones.map(b => b.parent), br = H.boneRoles(names, parents, c.state.roles);
      for (const pm of previewMeshes) {
        const m = pm.src, n = m.pos.length / 3, k = m.skinIdx ? 4 : 1;
        pm.base = new Float32Array(m.pos.length); pm.roleIdx = new Int16Array(n * k); pm.w = new Float32Array(n * k); pm.k = k;
        for (let i = 0; i < n; i++) {
          const p = fit.apply(H.rotate(R, [m.pos[3 * i], m.pos[3 * i + 1], m.pos[3 * i + 2]]));
          pm.base[3 * i] = p[0]; pm.base[3 * i + 1] = p[1]; pm.base[3 * i + 2] = p[2];
          if (m.skinIdx) for (let j = 0; j < 4; j++) {
            const bi = m.skinBones[m.skinIdx[4 * i + j]]; pm.roleIdx[4 * i + j] = bi >= 0 ? H.ROLES.indexOf(br[bi]) : -1; pm.w[4 * i + j] = m.skinW[4 * i + j];
          } else { pm.roleIdx[i] = m.owner >= 0 ? H.ROLES.indexOf(br[m.owner]) : 0; pm.w[i] = 1; }
        }
      }
    }
    function bounds(pts) {
      const mn = [Infinity, Infinity, 0], mx = [-Infinity, -Infinity, 0];
      for (const p of pts) { mn[0] = Math.min(mn[0], p[0]); mn[1] = Math.min(mn[1], p[1]); mx[0] = Math.max(mx[0], p[0]); mx[1] = Math.max(mx[1], p[1]); }
      return Number.isFinite(mn[0]) ? { min: mn, max: mx } : { min: [-1, 0, 0], max: [1, 2, 0] };
    }
    function makeView(kind) {
      const stage = q(`[data-rt-stage="${kind}"]`);
      const ov = doc.createElement("canvas"); ov.className = "ov"; stage.append(ov);
      const v = { stage, ov, ctx: ov.getContext("2d"), w: 1, h: 1, map: null, renderer: null, scene: null, camera: null, group: null };
      if (THREE) {
        v.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); v.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
        stage.insertBefore(v.renderer.domElement, ov);
        v.scene = new THREE.Scene(); v.scene.add(new THREE.HemisphereLight(0xffffff, 0x30364a, 2.0));
        const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(2, 4, 5); v.scene.add(sun);
        v.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -100, 100); v.camera.position.set(0, 0, 10);
        v.group = new THREE.Group(); v.scene.add(v.group);
      }
      return v;
    }
    function frameView(v, b) {
      const r = v.stage.getBoundingClientRect(); v.w = Math.max(1, r.width); v.h = Math.max(1, r.height);
      v.ov.width = v.w; v.ov.height = v.h;
      v.map = H.view(b, v.w, v.h);
      if (v.renderer) {
        v.renderer.setSize(v.w, v.h, false);
        const cx = (b.min[0] + b.max[0]) / 2, cy = (b.min[1] + b.max[1]) / 2, hw = v.w / 2 / v.map.s, hh = v.h / 2 / v.map.s;
        Object.assign(v.camera, { left: cx - hw, right: cx + hw, top: cy + hh, bottom: cy - hh }); v.camera.updateProjectionMatrix();
      }
    }
    function circle(ctx, map, p, r, color, fill, label) {
      const [x, y] = map.toScreen(p), rr = Math.max(4, r * map.s);
      ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
      if (label) { ctx.fillStyle = "#dfe4ec"; ctx.font = "10px system-ui"; ctx.fillText(label, x + rr + 3, y + 3); }
    }
    function bonesLines(ctx, map, pos, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      for (const [p, ch] of Object.entries(H.CHILD)) if (pos[p] && pos[ch]) {
        const a = map.toScreen(pos[p]), b = map.toScreen(pos[ch]); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
    }
    function redraw() {
      if (dead) return;
      const st = c.state;
      // donor view: the model, a dot on every bone, a coloured circle on every assigned one
      const dv = views.donor;
      if (dv && donor) {
        const rot = R || [[1, 0, 0], [0, 1, 0], [0, 0, 1]], pts = donor.bones.map(b => H.rotate(rot, b.pos));
        if (!donor.sample) {                                  // the mesh's extent frames the view (a head is above its bone)
          donor.sample = [];
          for (const m of donor.meshes) for (let i = 0; i < m.pos.length; i += 3 * Math.max(1, Math.floor(m.pos.length / 3 / 400)))
            donor.sample.push([m.pos[i], m.pos[i + 1], m.pos[i + 2]]);
        }
        frameView(dv, bounds(pts.concat(donor.sample.map(p => H.rotate(rot, p)))));
        if (dv.renderer) dv.renderer.render(dv.scene, dv.camera);
        const ctx = dv.ctx; ctx.clearRect(0, 0, dv.w, dv.h);
        const byBone = new Map(Object.entries(st.roles).map(([r, b]) => [b, r]));
        donor.bones.forEach((b, i) => {
          const role = byBone.get(b.name), p = pts[i];
          if (b.parent >= 0) { const a = dv.map.toScreen(pts[b.parent]), z = dv.map.toScreen(p); ctx.strokeStyle = "#ffffff30"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(z[0], z[1]); ctx.stroke(); }
          if (role) circle(ctx, dv.map, p, 0, COLORS[role], COLORS[role] + "55", H.LABELS[role]);
          else { const [x, y] = dv.map.toScreen(p); ctx.fillStyle = st.armed ? "#ffb46b" : "#8b93a3"; ctx.fillRect(x - 2, y - 2, 4, 4); }
        });
        dv.points = pts;
      }
      // target view: stock model / skeleton + the fitted donor, live, with the circles
      const tv = views.target;
      if (tv && fit) {
        const tr = H.roleTransforms(pivots, st.profile, tGround);
        for (const pm of previewMeshes) {
          H.applyPositions(pm.base, pm.roleIdx, pm.w, pm.k, tr, pm.attr.array);
          pm.attr.needsUpdate = true; pm.geo.computeVertexNormals(); pm.geo.computeBoundingSphere();
        }
        const hs = H.handles(pivots, st.profile, tGround);
        const pts = Object.values(tPos).concat(hs.map(h => h.at));
        frameView(tv, bounds(pts.concat([[0, tGround - 0.05 * H.frame(tPos, tGround).H, 0]])));
        if (tv.renderer) tv.renderer.render(tv.scene, tv.camera);
        const ctx = tv.ctx; ctx.clearRect(0, 0, tv.w, tv.h);
        bonesLines(ctx, tv.map, tPos, "#ffffff40");
        const g = tv.map.toScreen([0, tGround + st.profile.ground * H.frame(tPos, tGround).H, 0]);
        ctx.strokeStyle = "#ffffff30"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(0, g[1]); ctx.lineTo(tv.w, g[1]); ctx.stroke(); ctx.setLineDash([]);
        for (const h of hs) {
          if (h.kind === "head") { const [x, y] = tv.map.toScreen(h.centre); ctx.strokeStyle = "#ff6b8b88"; ctx.beginPath(); ctx.arc(x, y, h.ring * tv.map.s, 0, Math.PI * 2); ctx.stroke(); }
          const col = h.role ? COLORS[h.role] : "#ffd36b";
          circle(ctx, tv.map, h.at, h.r, col, drag && drag.h.id === h.id ? col + "aa" : col + "33",
            { length: "", head: "head", width: "", height: "height", ground: "ground" }[h.kind]);
        }
        tv.handles = hs;
      } else if (tv) {
        frameView(tv, bounds(Object.values(tPos)));
        if (tv.renderer) tv.renderer.render(tv.scene, tv.camera);
        tv.ctx.clearRect(0, 0, tv.w, tv.h); bonesLines(tv.ctx, tv.map, tPos, "#ffffff60");
        tv.ctx.fillStyle = "#ff8b8b"; tv.ctx.font = "12px system-ui";
        tv.ctx.fillText(donor ? "Assign the hips and the head to see the fit" : "Loading the donor…", 12, 20);
      }
    }
    function pointer(kind) {
      const v = views[kind], at = e => { const r = v.ov.getBoundingClientRect(); return v.map.toModel([e.clientX - r.left, e.clientY - r.top]); };
      v.ov.addEventListener("pointerdown", e => {
        if (!v.map) return;
        const p = at(e), tol = 6 / v.map.s;
        if (kind === "donor") {
          if (!donor || !v.points) return;
          let best = -1, bd = 10 / v.map.s;
          v.points.forEach((q2, i) => { const d = Math.hypot(q2[0] - p[0], q2[1] - p[1]); if (d < bd) { bd = d; best = i; } });
          if (best >= 0) { c.clickBone(donor.bones[best].name); refit(); schedule(); }
          return;
        }
        let h = H.hit(v.handles || [], p, tol);
        if (e.shiftKey) {                                    // Shift: move the part nearest the pointer
          const r = Object.entries(pivots).sort((a, b) => Math.hypot(a[1][0] - p[0], a[1][1] - p[1]) - Math.hypot(b[1][0] - p[0], b[1][1] - p[1]))[0];
          if (r) h = { id: "offset:" + r[0], kind: "offset", role: r[0], at: p, r: 0 };
        }
        if (!h) return;
        drag = { h, start: JSON.parse(JSON.stringify(c.state.profile)), from: p };
        try { v.ov.setPointerCapture(e.pointerId); } catch (err) { /* optional */ }
        e.preventDefault(); e.stopPropagation();
      });
      v.ov.addEventListener("pointermove", e => {
        if (!drag || kind !== "target") return;
        c.state.profile = drag.start;
        c.dragTo(Object.assign({}, drag.h, { from: drag.from }), at(e), pivots, tGround);
      });
      const end = () => { if (drag) { drag = null; c.settle(); schedule(); } };
      v.ov.addEventListener("pointerup", end); v.ov.addEventListener("pointercancel", end);
    }

    // ---- DOM events on the side panel ----
    el.addEventListener("input", e => {
      const s = e.target.closest("[data-rt-set]"); if (!s) return;
      c.setValue(s.dataset.rtSet, s.value);
      const out = s.parentElement.querySelector("output"), v = +s.value, path = s.dataset.rtSet;
      if (out) out.textContent = /rotate/.test(path) ? v.toFixed(0) + "°" : /offset|ground/.test(path) ? (v * 100).toFixed(1) + "%" : v.toFixed(2) + "×";
    });
    el.addEventListener("change", e => {
      const b = e.target.closest("[data-rt-bone]");
      if (b) { c.setRoleBone(b.dataset.rtBone, b.value); refit(); schedule(); return; }
      if (e.target.matches('[data-rt="slot"]')) c.setSlot(e.target.value).then(() => { refit(); schedule(); }).catch(err => ui.status("✗ " + err.message));
    });
    el.addEventListener("click", async e => {
      const arm = e.target.closest("[data-rt-arm]"); if (arm) { c.arm(arm.dataset.rtArm); schedule(); return; }
      const part = e.target.closest("[data-rt-part]"); if (part) { c.selectPart(part.dataset.rtPart); return; }
      const go = e.target.closest("[data-rt-go]"); if (!go) return;
      const what = go.dataset.rtGo;
      try {
        if (what === "close") { if (c.state.dirty && io.confirm && !io.confirm("Close without saving the retarget changes?")) return; dispose(); return; }
        if (what === "guess") { c.guess(); refit(); schedule(); return; }
        if (what === "part-reset") { c.resetPart(go.dataset.role); schedule(); return; }
        if (what === "save") await c.save("slot");
        if (what === "save-all") await c.save("game");
        if (what === "reset") { await c.reset("slot"); refit(); schedule(); }
        if (io.onSaved && /save/.test(what)) io.onSaved(c.state);
      } catch (err) { ui.status("✗ " + String(err.message || err).slice(0, 300)); }
    });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => schedule()) : null;
    function dispose() {
      dead = true; if (ro) ro.disconnect();
      for (const v of Object.values(views)) if (v && v.renderer) {
        v.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach(m => m.dispose()); });
        v.renderer.dispose();
      }
      el.remove();
    }

    // ---- load: profile, then the modules and both models ----
    (async () => {
      await c.load();
      try { const m = await loadThree(io); THREE = m.THREE; Loader = m.GLTFLoader; }
      catch (err) { ui.status("3D view unavailable (" + String(err.message || err).slice(0, 80) + "); the role list and sliders still work"); }
      if (dead) return;
      views.donor = makeView("donor"); views.target = makeView("target"); pointer("donor"); pointer("target");
      if (ro) { ro.observe(views.donor.stage); ro.observe(views.target.stage); }
      const url = u => (io.url ? io.url(u) : u);
      const load = async u => { const r = await fetch(url(u)); if (!r.ok) throw new Error(`model download returned ${r.status}`);
        return new Loader().parseAsync(await r.arrayBuffer(), ""); };
      // target: the slot's stock model when the collection has one, else a standard skeleton
      const ref = c.state.reference;
      q('[data-rt="target-name"]').textContent = ref ? ref.name : "standard skeleton";
      tPos = H.standardSkeleton(1.7); tGround = 0;
      if (THREE && ref && ref.model_url) {
        try {
          const g = await load(ref.model_url); if (dead) return;
          target = readModel(THREE, g);
          const raw = rolePositions(target, ref.roles, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]), Rt = H.facing(raw);
          const pos = rolePositions(target, ref.roles, Rt);
          if (pos.hip && pos.head) {
            tPos = pos;
            let gmin = Infinity; for (const m of target.meshes) for (let i = 0; i < m.pos.length; i += 3) gmin = Math.min(gmin, H.rotate(Rt, [m.pos[i], m.pos[i + 1], m.pos[i + 2]])[1]);
            tGround = Number.isFinite(gmin) ? gmin : 0;
            const holder = new THREE.Group(); holder.add(g.scene);
            holder.matrixAutoUpdate = false; holder.matrix.set(...Rt[0], 0, ...Rt[1], 0, ...Rt[2], 0, 0, 0, 0, 1); holder.matrixWorldNeedsUpdate = true;
            g.scene.traverse(o => { if (o.isMesh) { o.material = new THREE.MeshStandardMaterial({ color: 0x5b6472, transparent: true, opacity: 0.35, depthWrite: false }); } });
            views.target.group.add(holder);
          }
        } catch (err) { ui.status("Stock model unavailable (" + err.message + "); showing a standard skeleton"); }
      }
      if (THREE && c.state.view && c.state.view.model_url) {
        try {
          const g = await load(c.state.view.model_url); if (dead) return;
          donor = readModel(THREE, g);
          c.setBones(donor.bones.map(b => b.name));
          views.donor.group.add(g.scene);
          for (const m of donor.meshes) {
            const geo = new THREE.BufferGeometry(), attr = new THREE.BufferAttribute(new Float32Array(m.pos.length), 3);
            geo.setAttribute("position", attr); if (m.index) geo.setIndex(Array.from(m.index));
            const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x8fe6a8, transparent: true, opacity: 0.8, side: THREE.DoubleSide }));
            views.target.group.add(mesh); previewMeshes.push({ src: m, geo, attr, mesh });
          }
          refit();
          if (R) { const d = views.donor.group; d.matrixAutoUpdate = false; d.matrix.set(...R[0], 0, ...R[1], 0, ...R[2], 0, 0, 0, 0, 1); d.matrixWorldNeedsUpdate = true; }
        } catch (err) { ui.status("✗ donor model: " + String(err.message || err).slice(0, 200)); }
      }
      schedule();
    })().catch(err => ui.status("✗ " + String(err.message || err).slice(0, 300)));
    return { el, controller: c, dispose };
  }

  const api = { controller, open, rolesHTML, globalsHTML, partHTML, headerHTML, frameHTML, readModel, COLORS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxRetargetEditor = api;
})(typeof window !== "undefined" ? window : globalThis);
