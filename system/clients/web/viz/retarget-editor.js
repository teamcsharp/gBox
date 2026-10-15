// Retarget editor (gbox/retarget_profile.py): how one collection character is scaled and proportioned into one game.
// Left: the donor with a circle on every bone - arm a body role in the list, then click the bone that IS that role
// ("what is what"). Right: the target slot's stock model (or a standard skeleton at the game's proportions) with the
// donor fitted over it, live; drag the circles to stretch a limb, size the head, widen the shoulders, raise the
// figure or lift it off the ground (Shift-drag any joint moves that part). Save keeps it on the server per donor,
// game and slot; the next build of that slot (one swap or the whole cast) fits with it.
// Goals view (the default; the Fitting pop-up's R buttons open it): the donor and the target slot's own skeleton side by
// side, both laid out in a T-pose front view, a numbered translucent circle on every joint - the same number and colour
// on both sides is the same body role. Drag a donor circle to move that joint's pivot on the donor mesh (profile
// "joints"; the build moves the rig joint and re-derives the limb segments before fitting); click it to pick which
// donor bone it is. The target side shows the fitted donor live. "Save and rebuild this slot" saves, then queues the
// same characters call for this slot only (gbox/special_builds.py recipes), whose progress shows in the pop-up.
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

  const NUM = Object.fromEntries(H.GOALS.map((r, i) => [r, i + 1]));
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
  function boneOptions(state, role) {
    const bones = state.bones || [], bone = (state.roles || {})[role] || "";
    const opts = ['<option value="">(none)</option>'].concat(bones.map(b => `<option value="${ESC(b)}"${b === bone ? " selected" : ""}>${ESC(b)}</option>`));
    if (bone && !bones.includes(bone)) opts.push(`<option value="${ESC(bone)}" selected>${ESC(bone)} (not in model)</option>`);
    return opts.join("");
  }
  // the view switch over the two stages
  function tabsHTML(state) {
    return `<button type="button" class="act${state.mode === "goals" ? " pri" : ""}" data-rt-mode="goals" title="Both figures in a T-pose, a circle on every joint">Goals</button>
      <button type="button" class="act${state.mode === "fit" ? " pri" : ""}" data-rt-mode="fit" title="Bones, proportions and the fit over the stock model">Fit &amp; proportions</button>
      <button type="button" class="act${state.mode === "shape" ? " pri" : ""}" data-rt-mode="shape">Shape cage</button>
      <label class="rt-tp"><input type="checkbox" data-rt-tpose${state.tpose ? " checked" : ""}> T-pose</label>`;
  }
  // the selected circle: which donor bone it is (a list of every bone) and where its pivot moved
  function jointHTML(state) {
    const role = state.joint;
    if (!role) return '<div class="mut rt-hint">Click a circle to pick which donor bone it is; drag a circle on the donor to move that joint (the elbow guessed too high: drag it down to the real elbow).</div>';
    const j = H.jointOf(H.normalize(state.profile), role);
    return `<div class="rt-joint" data-rt-joint="${ESC(role)}"><b><i style="background:${COLORS[role]}"></i>${NUM[role] || ""} ${ESC(H.JOINT_LABELS[role] || role)}</b>
      <label class="rt-jb"><span>Donor bone</span><select data-rt-bone="${ESC(role)}">${boneOptions(state, role)}</select></label>
      ${[0, 1, 2].map(i => slider(`joints.${role}.${i}`, `Move ${"XYZ"[i]}`, -H.JOINT_RANGE, H.JOINT_RANGE, 0.001, j[i], "%")).join("")}
      <button type="button" class="act" data-rt-go="joint-reset" data-role="${ESC(role)}">Put this joint back</button></div>`;
  }
  // the numbered list of goals: donor bone -> target joint, moved joints marked
  function legendHTML(state) {
    const p = H.normalize(state.profile), tgt = ((state.goals || {}).target) || null;
    return H.GOALS.map(role => {
      const bone = (state.roles || {})[role] || "", moved = p.joints[role] ? " · moved" : "";
      const there = tgt ? (tgt[role] ? "" : " · not in the slot") : "";
      return `<div class="rt-goal${state.joint === role ? " sel" : ""}${bone ? "" : " miss"}" data-rt-joint-pick="${role}">
        <i style="background:${COLORS[role]}">${NUM[role]}</i><span>${ESC(H.JOINT_LABELS[role])}</span>
        <em>${ESC(bone || "unassigned")}${moved}${there}</em></div>`;
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
          <div class="rt-modes" data-rt-part-slot="tabs"></div>
          <div class="rt-view"><div class="rt-cap"><span data-rt="donor-cap">Donor</span> <span class="mut" data-rt="donor-hint"></span></div><div class="rt-stage" data-rt-stage="donor"></div></div>
          <div class="rt-view"><div class="rt-cap"><span data-rt="target-cap">Target</span> · <span data-rt="target-name">target</span> <span class="mut" data-rt="target-hint"></span></div><div class="rt-stage" data-rt-stage="target"></div></div>
        </div>
        <div class="rt-side scroll">
          <div class="rt-sec rt-goals-only" data-rt-part-slot="joint"></div>
          <div class="rt-sec rt-goals-only"><b>Goals</b> <span class="mut">donor bone → target joint</span><div data-rt-part-slot="legend"></div></div>
          <div class="rt-sec"><b>Shape before fitting</b><p class="mut">In Shape cage, drag circles over the source. The adjusted fit stays visible on the right.</p>
            <label>Cage depth <select data-rt-cage-slice><option value="0">Back</option><option value="1" selected>Middle</option><option value="2">Front</option></select></label>
            <button class="act" data-rt-go="shape-reset">Reset cage</button><label><input type="checkbox" data-rt-plant> Plant mesh feet at reference ground</label>
            <div class="mut" data-rt-fit-measures></div></div>
          <div class="rt-sec rt-shoe-controls"><b>Shoes and ground</b><p class="mut">Set ankle pivots in Goals. Separate each shoe from the leg with these source-height planes. Ground lift sets the target sole plane; Plant feet aligns the fitted soles in this pose.</p>
            <label><input type="checkbox" data-rt-shoes> Specify shoe boundaries</label>
            <label>Left shoe top (% of source body height)<input type="range" min="0" max="0.5" step="0.005" value="0.15" data-rt-shoe="l"><output data-shoe-value="l">15%</output></label>
            <label>Right shoe top (% of source body height)<input type="range" min="0" max="0.5" step="0.005" value="0.15" data-rt-shoe="r"><output data-shoe-value="r">15%</output></label>
            <p class="mut">This assigns same-side leg vertices below the plane to the foot; foot vertices above it return to the shin. Preview walking and crouching before approving. This does not change game collision or implement foot IK.</p></div>
          <div class="rt-sec"><b>Geometry approval</b><label><input type="checkbox" data-rt-preserve> No automatic geometry reduction</label><p class="mut">JGR/shared Ninja, SC2, DOA2 and FF7 try the edited mesh intact and stop with the allocation error if it cannot fit. Other writers may still reduce geometry.</p><label>Blender topology workspace<select data-rt-topology><option value="none">Original editable mesh</option><option value="2d">Local HOps 2D node cuts</option><option value="3d">Local HOps 3D node cuts</option><option value="voxel_study">Experimental voxel study</option></select></label><p class="mut">Node cuts require this PC's HOps asset and Blender 4.5+. Voxel copies start hidden and disabled; inspect skin weights and UVs before using a result.</p><button class="act" data-rt-go="workspace">Editable Blender workspace</button><p data-rt-workspace-status></p></div>
          <div class="rt-sec"><b>Proportions</b><div data-rt-part-slot="globals"></div></div>
          <div class="rt-sec" data-rt-part-slot="part"></div>
          <div class="rt-sec" data-rt-fit-history hidden></div>
          <div class="rt-sec" data-rt-textures></div>
          <div class="rt-sec" data-rt-photos></div>
          <div class="rt-sec"><b>What is what</b> <button type="button" class="act" data-rt-go="guess" title="Fill empty roles from bone names">Guess from names</button><div data-rt-part-slot="roles"></div></div>
        </div>
      </div>
      <div class="rt-f"><span data-rt="status" class="mut"></span>
        <button type="button" class="act" data-rt-go="reset">Reset</button>
        <button type="button" class="act" data-rt-go="save-all" title="Every slot of this game without its own profile">Save for the whole game</button>
        <button type="button" class="act pri" data-rt-go="save">Save for this slot</button>
        <button type="button" class="act" data-rt-go="save-rebuild" title="Save, then build this slot again (only this slot; nothing is launched); the progress shows in the Fitting pop-up">Save and rebuild this slot</button>
        <button type="button" class="act" data-rt-go="close">Close</button></div>`;
  }
  const CAPTIONS = {
    goals: { donor: ["Source · donor", "(drag a circle to move that joint; click it to pick its bone)"],
      target: ["Target · goals", "(the fitted donor, live)"] },
    shape: {donor:["Reference · original donor", "(drag cage circles; Alt-drag changes depth)"],target:["Adjusted · over stock reference", "(cage deformation before retargeting)"]},
    fit: { donor: ["Donor · bones", "(arm a role, click its bone)"], target: ["In the game", "(drag the circles; Shift-drag moves a part)"] } };

  // ---- the controller (no DOM) ------------------------------------------------------------
  // io: api(path, body?) -> data (throws), render(part, html), status(text), onChange(state)
  function controller(io, opts) {
    const st = { slug: opts.slug, name: opts.name || "", gid: opts.gid, title: opts.title || "", slot: opts.slot || "player",
      slots: [], view: null, reference: null, baseRoles: {}, roles: {}, guessed: {}, profile: H.normalize({}), bones: [],
      armed: null, part: null, dirty: false, savedNote: "", mode: opts.view === "fit" ? "fit" : "goals", tpose: true,
      joint: null, goals: null, rebuild: null };
    const q = () => `game_id=${encodeURIComponent(st.gid)}&slot=${encodeURIComponent(st.slot)}`;
    const changed = () => { io.onChange && io.onChange(st); };
    function renderAll() {
      io.render("header", headerHTML(st)); io.render("globals", globalsHTML(st.profile));
      io.render("part", partHTML(st.profile, st.part)); io.render("roles", rolesHTML(st));
      io.render("tabs", tabsHTML(st)); io.render("joint", jointHTML(st)); io.render("legend", legendHTML(st));
    }
    async function load() {
      io.status("Loading the profile…");
      const [v, ref, src, game, goals] = await Promise.all([
        io.api(`/api/characters/${encodeURIComponent(st.slug)}/retarget_profile?${q()}`),
        io.api(`/api/retarget/reference?${q()}`).catch(() => null),
        st.slots.length ? Promise.resolve(null) : io.api(`/api/cast_swap/sources?game_id=${encodeURIComponent(st.gid)}`).catch(() => null),
        st.title ? Promise.resolve(null) : io.api(`/api/catalog/${encodeURIComponent(st.gid)}`).catch(() => null),
        io.api(`/api/retarget/goals?${q()}`).catch(() => null)]);
      st.view = v; st.name = v.name || st.name; st.reference = ref && ref.reference;
      st.goals = goals && goals.goals && goals.goals.target ? goals.goals : null;
      if (game && game.title) st.title = game.title;
      if (src && Array.isArray(src.slots) && src.slots.length) {
        st.slots = src.slots.map(s => ({ slot: s.slot, name: s.name }));
        if (!st.slots.some(s => s.slot === st.slot)) st.slots.unshift({ slot: st.slot, name: st.slot });
      }
      st.baseRoles = Object.assign({}, v.rig_roles || {});
      const p = H.normalize(opts.draftProfile || v.resolved || {});
      st.roles = H.applyOverrides(st.baseRoles, p.roles); st.profile = p; st.dirty = !!opts.draftProfile;
      st.savedNote = v.profile ? "saved for this slot" : v.game_wide ? "using the game-wide profile" : "automatic fit (nothing saved)";
      renderAll();
      io.status(!H.issues(st.roles).ok ? `Assign ${H.issues(st.roles).missing.join(" and ")} first: the fit needs them.`
        : st.mode === "goals" ? "Drag the circles on the donor to where its joints really are; the fit on the right updates live."
          : "Drag the circles on the right; the fit updates live.");
      changed();
      return st;
    }
    function setMode(mode) { st.mode = ["fit","shape"].includes(mode) ? mode : "goals"; io.render("tabs", tabsHTML(st)); changed(); }
    function setTpose(on) { st.tpose = !!on; io.render("tabs", tabsHTML(st)); changed(); }
    function selectJoint(role) {                              // a circle clicked: its bone list and its move
      st.joint = H.GOALS.includes(role) ? role : null;
      io.render("joint", jointHTML(st)); io.render("legend", legendHTML(st)); changed();
    }
    function dragJoint(circle, from, to, height, startJoint) { // a donor circle dragged in the Goals view
      st.profile = H.dragJoint(st.profile, circle, from, to, height, startJoint); st.dirty = true; st.joint = circle.role;
      changed();
    }
    function resetJoint(role) {
      st.profile = H.resetJoint(st.profile, role); st.dirty = true;
      io.render("joint", jointHTML(st)); io.render("legend", legendHTML(st)); changed();
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
      io.render("roles", rolesHTML(st)); io.render("legend", legendHTML(st));
      if (st.joint) io.render("joint", jointHTML(st));
      changed();
    }
    function clickBone(bone) {                                // a bone dot clicked in the donor view
      if (!st.armed) { const r = Object.entries(st.roles).find(([, b]) => b === bone); if (r) selectPart(r[0]); return null; }
      const role = st.armed; setRoleBone(role, bone); io.status(`${H.LABELS[role]} = ${bone}`); return role;
    }
    function selectPart(role) { st.part = role; io.render("part", partHTML(st.profile, role)); io.render("roles", rolesHTML(st)); }
    function setValue(path, value) {                          // "height" | "adjust.l_fore.length" | "adjust.head.offset.1" | "joints.l_fore.1"
      const parts = path.split("."), v = Number(value);
      if (parts[0] === "joints") {
        const j = H.jointOf(H.normalize(st.profile), parts[1]); j[+parts[2]] = v;
        st.profile = H.setJoint(st.profile, parts[1], j);
      } else if (parts[0] === "adjust") {
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
    function settle() {
      io.render("globals", globalsHTML(st.profile)); io.render("part", partHTML(st.profile, st.part));
      io.render("joint", jointHTML(st)); io.render("legend", legendHTML(st));
    }
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
    // the characters call that builds this slot again, alone: the call that made the build (the pop-up's job, else the
    // game's special-builds recipe that holds this donor in this slot) narrowed to this slot; launch=false, rebuild=true
    async function rebuildRecipe() {
      const who = [{ slot: st.slot, character: st.slug }], rec = opts.recipe || null;
      let base = rec && rec.input && ["cast_swap", "use"].includes(rec.input.op) ? rec.input : null;
      if (!base) {
        try {
          const sb = await io.api(`/api/games/${encodeURIComponent(st.gid)}/special_builds`);
          for (const g of (sb && sb.groups) || []) for (const b of g.builds || []) {
            const i = b.rebuild_recipe && b.rebuild_recipe.input;
            if (!base && i && i.op === "cast_swap" && (i.assignments || []).some(a => a.slot === st.slot && a.character === st.slug)) base = i;
          }
        } catch (err) { /* no special builds: a recipe from the donor's own source below */ }
      }
      if (base && base.op === "use")
        return { tool: "characters", input: { op: "use", character: st.slug, game_id: st.gid, slot: st.slot, launch: false, rebuild: true } };
      const source = (base && base.source) || ((st.view || {}).source || {}).game_id || st.slug;
      return { tool: "characters", input: Object.assign({ op: "cast_swap", target_game: st.gid, source, mapping: (base && base.mapping) || "auto",
        seed: (base && base.seed) || "", slots: st.slot, assignments: who, launch: false, rebuild: true },
        base && base.lead_character && (!base.lead_slot || base.lead_slot===st.slot) ? {lead_character:st.slug,lead_slot:st.slot} : {},
        base && base.strict_cutscenes ? { strict_cutscenes: true } : {}) };
    }
    async function saveAndRebuild() {
      if(st.texturePending)throw Error("Accept or reject the texture candidate before rebuilding.");
      const v = await save("slot");
      if (!v) return null;
      const recipe = await rebuildRecipe();
      io.status("Queuing the rebuild of " + st.slot + "…");
      const r = await io.api(`/api/games/${encodeURIComponent(st.gid)}/special_builds/rebuild`, { recipes: [recipe] });
      st.rebuild = Object.assign({ recipe }, r);
      const id = (r && r.job_ids || [])[0];
      io.status(id ? `✓ Saved; rebuilding ${st.slot} (job ${id}): the Fitting pop-up follows it.`
        : `✓ Saved, but the rebuild was not queued: ${((r && r.skipped) || []).map(s => s.reason).join("; ") || "no job"}`);
      if (id && io.onRebuild) io.onRebuild(st.rebuild, st);
      return st.rebuild;
    }
    return { state: st, load, setBones, guess, arm, setRoleBone, clickBone, selectPart, setValue, resetPart, dragTo, settle,
      payload, save, reset, setSlot, renderAll, setMode, setTpose, selectJoint, dragJoint, resetJoint, rebuildRecipe, saveAndRebuild };
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
    #rtedit .rt-shoe-controls label{display:block;margin:8px 0}#rtedit .rt-shoe-controls input[type=range]{display:block;width:100%}
    #rtedit .rt-sl input{width:100%;accent-color:var(--acc,#4f8cff)}#rtedit .rt-sl output{text-align:right;font-variant-numeric:tabular-nums}
    #rtedit .rt-role{display:grid;grid-template-columns:10px 96px 1fr 44px 52px;gap:4px;align-items:center;padding:1px 2px;border-radius:4px}
    #rtedit .rt-role i{width:9px;height:9px;border-radius:50%}#rtedit .rt-role select{min-width:0;font-size:11px}
    #rtedit .rt-role .rt-rn{cursor:pointer;font-size:11.5px}#rtedit .rt-role.sel{background:#ffffff10}#rtedit .rt-role.armed{outline:1px solid #ffb46b}
    #rtedit .rt-role.miss .rt-rn,#rtedit .rt-role.miss em{color:#ff8b8b}#rtedit .rt-role em{font-size:10px;color:#7d8696}
    #rtedit .rt-role button{font-size:10.5px;padding:1px 4px}#rtedit .rt-f{display:flex;gap:6px;align-items:center;padding:6px 10px;border-top:1px solid var(--line,#2c3340)}
    #rtedit .rt-f [data-rt=status]{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #rtedit .rt-part b{display:block;margin:2px 0}#rtedit .rt-hint{font-size:11px}
    #rtedit .rt-views{flex-wrap:wrap}#rtedit .rt-modes{flex:1 0 100%;display:flex;gap:6px;align-items:center;font-size:11px}
    #rtedit .rt-modes .rt-tp{margin-left:auto;display:flex;gap:4px;align-items:center}#rtedit .rt-view{min-height:0;height:calc(100% - 30px)}
    #rtedit[data-mode=fit] .rt-goals-only,#rtedit[data-mode=shape] .rt-goals-only{display:none}
    #rtedit .rt-joint b{display:flex;gap:6px;align-items:center;margin:2px 0}#rtedit .rt-joint b i,#rtedit .rt-goal i{width:16px;height:16px;border-radius:50%;
      display:inline-block;font:700 9px/16px ui-monospace,monospace;text-align:center;color:#101318;font-style:normal;flex:none}
    #rtedit .rt-jb{display:grid;grid-template-columns:92px 1fr;gap:4px;align-items:center;font-size:11px;margin-bottom:3px}#rtedit .rt-jb select{min-width:0;font-size:11px}
    #rtedit .rt-goal{display:grid;grid-template-columns:18px 104px 1fr;gap:4px;align-items:center;padding:1px 2px;border-radius:4px;cursor:pointer;font-size:11px}
    #rtedit .rt-goal.sel{background:#ffffff14}#rtedit .rt-goal.miss em{color:#ff8b8b}#rtedit .rt-goal em{font-size:10px;color:#7d8696;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`;

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
        prop:!!(o.userData?.gbox_prop), material:o.material, uv:g.attributes.uv?.array,
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
    const pending=new Set(),pendingReview=(kind,on)=>{on?pending.add(kind):pending.delete(kind);c.state.texturePending=!!pending.size;};
    const accepted=result=>{const draft=H.normalize(c.state.profile),slot=c.state.slot;dispose();open(doc,io,{...opts,slug:result.variant,name:result.name,slot,draftProfile:draft});};
    const textures=root.GBoxTextureReview?.mount(q('[data-rt-textures]'),{api:io.api,url:u=>io.url?io.url(u):u},{slug:opts.slug,onPreview:showTextureCandidate,
      onPending:on=>pendingReview('texture',on),onAccepted:accepted});
    const photos=root.GBoxPhotoSkin?.mount(q('[data-rt-photos]'),{api:io.api,url:u=>io.url?io.url(u):u},{slug:opts.slug,onPreview:showTextureCandidate,
      onPending:on=>pendingReview('photo',on),onAccepted:accepted});
    el.dataset.mode = c.state.mode;
    let raf = 0;
    function schedule() { if (!raf && !dead) raf = requestAnimationFrame(() => { raf = 0; redraw(); }); }

    // ---- scene data (filled once the models load) ----
    const I = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    let THREE = null, Loader = null, donor = null, target = null, R = null, donorRest = {}, donorPos = {}, fit = null, lfit = null,
      cageBounds = null, shapeKey = null, shoeKey = null, cageSlice=1, pivots = {}, tPos = {}, tGround = 0, dGround = 0, Hd = 1, jointsKey = null, donorScene = null, refHolder = null;
    let previewMeshes = [], posedMeshes = [], drag = null;
    let textureCandidate=null,textureRequest=0;
    function disposeCandidateScene(scene) {
      const textures=new Set();
      scene.traverse(o=>{
        o.geometry?.dispose();for(const m of [].concat(o.material||[])){
          for(const value of Object.values(m))if(value?.isTexture)textures.add(value);m.dispose();
        }
      });
      for(const texture of textures)texture.dispose();
    }
    function disposeTextureCandidate(){if(textureCandidate)disposeCandidateScene(textureCandidate.scene);textureCandidate=null;}
    async function showTextureCandidate(result) {
      const request=++textureRequest;
      if(!donor||!Loader||!previewMeshes.length)throw Error('Wait for the character model to finish loading');
      if(result && textureCandidate?.sha!==result.candidate){
        const path='/api/artifacts/'+encodeURIComponent(result.candidate);
        const response=await fetch(io.url?io.url(path):path);
        if(!response.ok)throw Error('Candidate download returned '+response.status);
        const gltf=await new Loader().parseAsync(await response.arrayBuffer(),'');
        if(dead||request!==textureRequest){disposeCandidateScene(gltf.scene);return;}
        const model=readModel(THREE,gltf);
        if(model.meshes.length!==donor.meshes.length || model.meshes.some((m,i)=>m.pos.length!==donor.meshes[i].pos.length)){
          disposeCandidateScene(gltf.scene);throw Error('Candidate meshes do not match the original donor');
        }
        disposeTextureCandidate();textureCandidate={sha:result.candidate,scene:gltf.scene,model};
      }
      if(dead||request!==textureRequest)return;
      previewMeshes.forEach((pm,i)=>{
        const source=result?textureCandidate.model.meshes[i].material:pm.src.material;
        const material=source?[].concat(source)[0].clone():new THREE.MeshStandardMaterial({color:0x8fe6a8,side:THREE.DoubleSide});
        pm.mesh.material.dispose();pm.mesh.material=material;
      });
      c.state.texturePreview=result?'candidate':'original';schedule();
    }
    function rolePositions(model, roles, rot) {
      const out = {};
      for (const [role, bone] of Object.entries(roles || {})) {
        const b = model.bones.find(x => x.name === bone); if (b) out[role] = H.rotate(rot, b.pos);
      }
      return out;
    }
    function refit() {                                        // roles changed: facing, rest joints, per-vertex roles
      if (!donor) return;
      R = H.facing(rolePositions(donor, c.state.roles, I));
      donorRest = rolePositions(donor, c.state.roles, R);
      let lo = Infinity, hi = -Infinity;                      // the donor's height: the unit of a joint move
      for (const m of donor.meshes) for (let i = 0; i < m.pos.length; i += 3) {
        const y = R[1][0] * m.pos[i] + R[1][1] * m.pos[i + 1] + R[1][2] * m.pos[i + 2]; if (y < lo) lo = y; if (y > hi) hi = y;
      }
      dGround = Number.isFinite(lo) ? lo : 0; Hd = Number.isFinite(hi - lo) && hi > lo ? hi - lo : 1;
      const names = donor.bones.map(b => b.name), parents = donor.bones.map(b => b.parent), br = H.boneRoles(names, parents, c.state.roles);
      for (const pm of previewMeshes) {
        const m = pm.src, n = m.pos.length / 3, k = m.skinIdx ? 4 : 1;
        pm.rest = new Float32Array(m.pos.length); pm.base = new Float32Array(m.pos.length); pm.k = k;
        pm.roles0 = new Array(n * k); pm.w = new Float32Array(n * k); pm.roleIdx = new Int16Array(n * k);
        for (let i = 0; i < n; i++) {
          const p = H.rotate(R, [m.pos[3 * i], m.pos[3 * i + 1], m.pos[3 * i + 2]]);
          pm.rest[3 * i] = p[0]; pm.rest[3 * i + 1] = p[1]; pm.rest[3 * i + 2] = p[2];
          if (m.skinIdx) for (let j = 0; j < 4; j++) {
            const bi = m.skinBones[m.skinIdx[4 * i + j]]; pm.roles0[4 * i + j] = bi >= 0 ? br[bi] : null; pm.w[4 * i + j] = m.skinW[4 * i + j];
          } else { pm.roles0[i] = m.owner >= 0 ? br[m.owner] : "hip"; pm.w[i] = 1; }
        }
      }
      const body=previewMeshes.filter(pm=>!pm.src.prop).flatMap(pm=>Array.from(pm.rest));
      const mn=[Infinity,Infinity,Infinity],mx=[-Infinity,-Infinity,-Infinity];for(let i=0;i<body.length;i+=3)for(let a=0;a<3;a++){mn[a]=Math.min(mn[a],body[i+a]);mx[a]=Math.max(mx[a],body[i+a]);}
      cageBounds={min:mn,max:mx};shapeKey=null;
      jointsKey = null;
      rejoint();
    }
    // joint moves changed: the moved pivots, the limb segments they re-derive (retarget_profile.move_joints), the fits
    function rejoint() {
      jointsKey = JSON.stringify(H.normalize(c.state.profile).joints);
      shapeKey = JSON.stringify(c.state.profile.lattice||{});
      for(const pm of previewMeshes)pm.shaped=pm.src.prop?pm.rest:H.deformCage(pm.rest,c.state.profile,cageBounds,Hd);
      shoeKey=JSON.stringify(c.state.profile.shoe_tops||{});
      let shoeFloor=Infinity,shoeTop=-Infinity;
      for(const pm of previewMeshes)if(!pm.src.prop)for(let i=1;i<pm.shaped.length;i+=3){shoeFloor=Math.min(shoeFloor,pm.shaped[i]);shoeTop=Math.max(shoeTop,pm.shaped[i]);}
      if (!donor || !donorRest.hip || !donorRest.head) { fit = lfit = null; return; }
      donorPos = H.movedPositions(donorRest, c.state.profile, Hd);
      fit = H.baseFit(donorPos, dGround, tPos, tGround);
      pivots = Object.fromEntries(Object.entries(donorPos).map(([r, p]) => [r, fit.apply(p)]));
      lfit = H.limbFit(donorPos, dGround, tPos, tGround);
      for (const pm of previewMeshes) {
        const n = pm.rest.length / 3, k = pm.k, own = new Array(n);
        for (let i = 0; i < n; i++) {                         // the strongest influence's role decides the segment
          let best = 0; for (let j = 1; j < k; j++) if (pm.w[i * k + j] > pm.w[i * k + best]) best = j;
          own[i] = pm.roles0[i * k + best];
          const p = fit.apply([pm.shaped[3 * i], pm.shaped[3 * i + 1], pm.shaped[3 * i + 2]]);
          pm.base[3 * i] = p[0]; pm.base[3 * i + 1] = p[1]; pm.base[3 * i + 2] = p[2];
        }
        let now = H.resegment(pm.rest, own, donorRest, donorPos);
        if(!pm.src.prop)now=H.shoeRoles(pm.shaped,now,c.state.profile,shoeFloor,shoeTop-shoeFloor);
        for (let i = 0; i < n; i++) for (let j = 0; j < k; j++) {
          let r = pm.roles0[i * k + j];
          if (now[i] !== own[i] && (r === own[i] || r === now[i])) r = now[i];   // the swept influences follow
          pm.roleIdx[i * k + j] = r ? H.ROLES.indexOf(r) : -1;
        }
      }
    }
    function bounds(pts) {
      const mn = [Infinity, Infinity, 0], mx = [-Infinity, -Infinity, 0];
      for (const p of pts) { mn[0] = Math.min(mn[0], p[0]); mn[1] = Math.min(mn[1], p[1]); mx[0] = Math.max(mx[0], p[0]); mx[1] = Math.max(mx[1], p[1]); }
      return Number.isFinite(mn[0]) ? { min: mn, max: mx } : { min: [-1, 0, 0], max: [1, 2, 0] };
    }
    function samples(arr, max = 400) {                        // a few points of a flat xyz array (view framing)
      const out = [], step = 3 * Math.max(1, Math.floor(arr.length / 3 / max));
      for (let i = 0; i + 2 < arr.length; i += step) out.push([arr[i], arr[i + 1], arr[i + 2]]);
      return out;
    }
    function makeView(kind) {
      const stage = q(`[data-rt-stage="${kind}"]`);
      const ov = doc.createElement("canvas"); ov.className = "ov"; stage.append(ov);
      const v = { stage, ov, ctx: ov.getContext("2d"), w: 1, h: 1, map: null, renderer: null, scene: null, camera: null, group: null, posed: null };
      if (THREE) {
        v.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); v.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
        stage.insertBefore(v.renderer.domElement, ov);
        v.scene = new THREE.Scene(); v.scene.add(new THREE.HemisphereLight(0xffffff, 0x30364a, 2.0));
        const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(2, 4, 5); v.scene.add(sun);
        v.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -100, 100); v.camera.position.set(0, 0, 10);
        v.group = new THREE.Group(); v.scene.add(v.group);
        v.posed = new THREE.Group(); v.scene.add(v.posed);   // the Goals view's T-posed donor (editor frame)
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
    function goalCircle(ctx, map, g, selected) {               // the references' translucent joint circle + centre dot
      const [x, y] = map.toScreen(g.at), rr = Math.max(7, g.r * map.s), col = COLORS[g.role];
      ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.fillStyle = col + (selected ? "66" : "38"); ctx.fill();
      ctx.lineWidth = selected ? 3 : 1.5; ctx.strokeStyle = selected ? "#ffffff" : col; ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
      ctx.fillStyle = "#dfe4ec"; ctx.font = "700 10px ui-monospace,monospace"; ctx.fillText(String(g.n), x + rr + 2, y - rr + 8);
    }
    function bonesLines(ctx, map, pos, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      for (const [p, ch] of Object.entries(H.CHILD)) if (pos[p] && pos[ch]) {
        const a = map.toScreen(pos[p]), b = map.toScreen(pos[ch]); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
    }
    function captions() {
      const cap = CAPTIONS[c.state.mode], set = (k, t) => { const n = q(`[data-rt="${k}"]`); if (n && n.textContent !== t) n.textContent = t; };
      set("donor-cap", cap.donor[0]); set("donor-hint", cap.donor[1]); set("target-cap", cap.target[0]); set("target-hint", cap.target[1]);
      if (el.dataset.mode !== c.state.mode) el.dataset.mode = c.state.mode;
    }
    function updateMesh(pm, src, tr) {
      H.applyPositions(src, pm.roleIdx || pm.src.roleIdx, pm.w || pm.src.w, pm.k || pm.src.k, tr, pm.attr.array);
      pm.attr.needsUpdate = true; pm.geo.computeVertexNormals(); pm.geo.computeBoundingSphere();
    }
    function redraw() {
      if (dead) return;
      const st = c.state, goals = st.mode === "goals";
      captions();
      const plant=q("[data-rt-plant]");if(plant)plant.checked=!!st.profile.plant_feet;
      q('[data-rt-preserve]').checked=!!st.profile.preserve_geometry;
      q('[data-rt-shoes]').checked=!!st.profile.shoe_tops;
      for(const side of ['l','r']){const input=q('[data-rt-shoe="'+side+'"]');input.disabled=!st.profile.shoe_tops;input.value=st.profile.shoe_tops?.[side]??.15;q('[data-shoe-value="'+side+'"]').textContent=(100*+input.value).toFixed(1)+'%';}
      if (donor && (JSON.stringify(H.normalize(st.profile).joints) !== jointsKey || JSON.stringify(st.profile.lattice||{}) !== shapeKey || JSON.stringify(st.profile.shoe_tops||{})!==shoeKey)) rejoint();
      if (donorScene) donorScene.visible = !goals;
      if (refHolder) refHolder.visible = !goals;
      for (const pm of posedMeshes) pm.mesh.visible = goals;
      const dv = views.donor;
      if (dv && donor && goals && donorRest.hip) {
        // Goals, source side: the donor T-posed about its rig's joints, a numbered circle on every joint (moved ones too)
        const tp = H.tPose(donorRest, st.tpose), pts = [];
        for (const pm of posedMeshes) { updateMesh(pm, pm.src.rest, tp); pts.push(...samples(pm.attr.array, 300)); }
        const cs = H.goalCircles(donorPos, { rest: donorRest, tpose: st.tpose, ground: dGround });
        frameView(dv, bounds(pts.concat(cs.map(g => g.at))));
        if (dv.renderer) dv.renderer.render(dv.scene, dv.camera);
        const ctx = dv.ctx; ctx.clearRect(0, 0, dv.w, dv.h);
        bonesLines(ctx, dv.map, Object.fromEntries(cs.map(g => [g.role, g.at])), "#ffffff55");
        for (const g of cs) goalCircle(ctx, dv.map, g, st.joint === g.role);
        dv.circles = cs;
      } else if (dv && donor) {
        // donor view: the model, a dot on every bone, a coloured circle on every assigned one
        const rot = R || I, pts = donor.bones.map(b => H.rotate(rot, b.pos));
        if (!donor.sample) {                                  // the mesh's extent frames the view (a head is above its bone)
          donor.sample = [];
          for (const m of donor.meshes) donor.sample.push(...samples(m.pos, 400));
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
        dv.points = pts; dv.circles = null;
        if(st.profile.shoe_tops){for(const [side,fraction] of Object.entries(st.profile.shoe_tops)){
          const yy=dv.map.toScreen([0,dGround+fraction*Hd,0])[1];ctx.strokeStyle=side==='l'?'#f7c45e':'#65e6ff';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(0,yy);ctx.lineTo(dv.w,yy);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=ctx.strokeStyle;ctx.fillText((side==='l'?'Left':'Right')+' shoe top',8,yy-4);
        }}
        if(st.mode === "shape" && cageBounds){
          const cs=[];for(let y=0;y<3;y++)for(let x=0;x<3;x++){const i=x+3*y+9*cageSlice,base=H.latticePoint(i,cageBounds),d=st.profile.lattice?.offsets?.[i]||[0,0,0];cs.push({id:i,at:base.map((v,a)=>v+d[a]*Hd),r:Hd*.025});}
          for(const g of cs)circle(ctx,dv.map,g.at,g.r,"#ffce66","#ffce6644",String(g.id));dv.cage=cs;
        }
      }
      const tv = views.target;
      if (tv && goals) {
        // Goals, target side: the slot's own skeleton T-posed with the same numbered circles, the fitted donor over it
        const tp = H.tPose(tPos, st.tpose), pts = [];
        if (lfit) {
          const tr = H.compose(tp, H.compose(H.roleTransforms(lfit.pivots, st.profile, tGround), lfit));
          for (const pm of previewMeshes) updateMesh(pm, pm.shaped||pm.rest, tr);
          plantFeet();
          for (const pm of previewMeshes) pts.push(...samples(pm.attr.array, 300));
        }
        const cs = H.goalCircles(tPos, { tpose: st.tpose, ground: tGround });
        frameView(tv, bounds(pts.concat(cs.map(g => g.at))));
        if (tv.renderer) tv.renderer.render(tv.scene, tv.camera);
        const ctx = tv.ctx; ctx.clearRect(0, 0, tv.w, tv.h);
        bonesLines(ctx, tv.map, tp.pos, "#ffffff55");
        for (const g of cs) goalCircle(ctx, tv.map, g, st.joint === g.role);
        if (!lfit) { ctx.fillStyle = "#ff8b8b"; ctx.font = "12px system-ui"; ctx.fillText(donor ? "Assign the hips and the head to see the fit" : "Loading the donor…", 12, 20); }
        tv.circles = cs; tv.handles = null;
      } else if (tv && fit) {
        // target view: stock model / skeleton + the fitted donor, live, with the circles
        const tr = H.roleTransforms(pivots, st.profile, tGround);
        for (const pm of previewMeshes) updateMesh(pm, pm.base, tr);
        plantFeet();
        const hs = H.handles(pivots, st.profile, tGround);
        const pts = Object.values(tPos).concat(hs.map(h => h.at));
        frameView(tv, bounds(pts.concat([[0, tGround - 0.05 * H.frame(tPos, tGround).H, 0]])));
        if (tv.renderer) tv.renderer.render(tv.scene, tv.camera);
        const ctx = tv.ctx; ctx.clearRect(0, 0, tv.w, tv.h);
        bonesLines(ctx, tv.map, tPos, "#ffffff40");
        const measure=q('[data-rt-fit-measures]');if(measure){let low=Infinity;for(const pm of previewMeshes)for(let i=1;i<pm.attr.array.length;i+=3)low=Math.min(low,pm.attr.array[i]);measure.textContent=Number.isFinite(low)?`Lowest mesh point: ${((low-tGround)/Math.max(H.frame(tPos,tGround).H,1e-9)*100).toFixed(1)}% of reference height above ground. Check animated poses before approving.`:'No mesh measurement.';}
        const g = tv.map.toScreen([0, tGround + st.profile.ground * H.frame(tPos, tGround).H, 0]);
        ctx.strokeStyle = "#ffffff30"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(0, g[1]); ctx.lineTo(tv.w, g[1]); ctx.stroke(); ctx.setLineDash([]);
        for (const h of hs) {
          if (h.kind === "head") { const [x, y] = tv.map.toScreen(h.centre); ctx.strokeStyle = "#ff6b8b88"; ctx.beginPath(); ctx.arc(x, y, h.ring * tv.map.s, 0, Math.PI * 2); ctx.stroke(); }
          const col = h.role ? COLORS[h.role] : "#ffd36b";
          circle(ctx, tv.map, h.at, h.r, col, drag && drag.h && drag.h.id === h.id ? col + "aa" : col + "33",
            { length: "", head: "head", width: "", height: "height", ground: "ground" }[h.kind]);
        }
        tv.handles = hs; tv.circles = null;
      } else if (tv) {
        frameView(tv, bounds(Object.values(tPos)));
        if (tv.renderer) tv.renderer.render(tv.scene, tv.camera);
        tv.ctx.clearRect(0, 0, tv.w, tv.h); bonesLines(tv.ctx, tv.map, tPos, "#ffffff60");
        tv.ctx.fillStyle = "#ff8b8b"; tv.ctx.font = "12px system-ui";
        tv.ctx.fillText(donor ? "Assign the hips and the head to see the fit" : "Loading the donor…", 12, 20);
        tv.handles = tv.circles = null;
      }
    }
    function plantFeet() {
      if(!c.state.profile.plant_feet)return;
      let floor=Infinity;
      for(const pm of previewMeshes)if(!pm.src.prop)for(let i=0;i<pm.roleIdx.length/pm.k;i++){
        let best=0;for(let k=1;k<pm.k;k++)if(pm.w[i*pm.k+k]>pm.w[i*pm.k+best])best=k;
        if(["l_foot","r_foot"].includes(H.ROLES[pm.roleIdx[i*pm.k+best]]))floor=Math.min(floor,pm.attr.array[i*3+1]);
      }
      if(Number.isFinite(floor)){
        const lift=tGround+c.state.profile.ground*H.frame(tPos,tGround).H-floor;
        for(const pm of previewMeshes){for(let i=1;i<pm.attr.array.length;i+=3)pm.attr.array[i]+=lift;pm.attr.needsUpdate=true;pm.geo.computeBoundingSphere();}
      }
    }
    function nearest(list, p, tol) {                          // the goal circle under the pointer
      let best = null, bd = Infinity;
      for (const g of list || []) { const d = Math.hypot(g.at[0] - p[0], g.at[1] - p[1]); if (d <= g.r + tol && d < bd) { best = g; bd = d; } }
      return best;
    }
    function pointer(kind) {
      const v = views[kind], at = e => { const r = v.ov.getBoundingClientRect(); return v.map.toModel([e.clientX - r.left, e.clientY - r.top]); };
      v.ov.addEventListener("pointerdown", e => {
        if (!v.map) return;
        const p = at(e), tol = 6 / v.map.s;
        if(c.state.mode === "shape" && kind === "donor"){
          const g=nearest(v.cage,p,tol);if(!g)return;drag={kind:"cage",g,from:p,start:(c.state.profile.lattice?.offsets?.[g.id]||[0,0,0]).slice(),map:v.map};try{v.ov.setPointerCapture(e.pointerId);}catch(err){/* optional */}e.preventDefault();e.stopPropagation();return;
        }
        if (c.state.mode === "goals") {                      // Goals: drag a donor circle; click either side's to pick it
          const g = nearest(v.circles, p, tol);
          if (!g) return;
          drag = { kind: "joint", side: kind, g, from: p, x0: e.clientX, y0: e.clientY, moved: false,
            start: H.jointOf(H.normalize(c.state.profile), g.role) };
          try { v.ov.setPointerCapture(e.pointerId); } catch (err) { /* optional */ }
          e.preventDefault(); e.stopPropagation();
          return;
        }
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
        if (!drag) return;
        if(drag.kind === "cage"){
          if(kind!=="donor")return;const rect=v.ov.getBoundingClientRect(),to=drag.map.toModel([e.clientX-rect.left,e.clientY-rect.top]);
          const offsets={...(c.state.profile.lattice?.offsets||{})};offsets[drag.g.id]=drag.start.map((d,a)=>Math.max(-.25,Math.min(.25,d+(e.altKey?(a===2?(to[0]-drag.from[0])/Hd:0):(a<2?(to[a]-drag.from[a])/Hd:0)))));
          c.state.profile=H.normalize({...c.state.profile,lattice:{offsets}});c.state.dirty=true;schedule();return;
        }
        if (drag.kind === "joint") {
          if (drag.side !== "donor" || kind !== "donor") return;
          if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 3) return;
          drag.moved = true;
          c.dragJoint(drag.g, drag.from, at(e), Hd, drag.start);
          return;
        }
        if (kind !== "target") return;
        c.state.profile = drag.start;
        c.dragTo(Object.assign({}, drag.h, { from: drag.from }), at(e), pivots, tGround);
      });
      const end = () => {
        if (!drag) return;
        const d = drag; drag = null;
        if (d.kind === "joint") {                            // a click (or the end of a drag): that joint's bone list
          c.selectJoint(d.g.role);
          if (!d.moved) { const s = q(`[data-rt-joint] select`); if (s && s.focus) s.focus(); }
        }
        c.settle(); schedule();
      };
      v.ov.addEventListener("pointerup", end); v.ov.addEventListener("pointercancel", end);
    }

    // ---- DOM events on the side panel ----
    el.addEventListener("input", e => {
      if(e.target.matches('[data-rt-shoe]')){const side=e.target.dataset.rtShoe;c.state.profile=H.normalize({...c.state.profile,shoe_tops:{...c.state.profile.shoe_tops,[side]:+e.target.value}});c.state.dirty=true;schedule();return;}
      const s = e.target.closest("[data-rt-set]"); if (!s) return;
      c.setValue(s.dataset.rtSet, s.value);
      const out = s.parentElement.querySelector("output"), v = +s.value, path = s.dataset.rtSet;
      if (out) out.textContent = /rotate/.test(path) ? v.toFixed(0) + "°" : /offset|ground|joints/.test(path) ? (v * 100).toFixed(1) + "%" : v.toFixed(2) + "×";
    });
    el.addEventListener("change", e => {
      const b = e.target.closest("[data-rt-bone]");
      if (b) { c.setRoleBone(b.dataset.rtBone, b.value); refit(); schedule(); return; }
      if(e.target.matches('[data-rt-cage-slice]')){cageSlice=+e.target.value;schedule();return;}
      if(e.target.matches('[data-rt-plant]')){c.state.profile=H.normalize({...c.state.profile,plant_feet:e.target.checked});c.state.dirty=true;schedule();return;}
      if(e.target.matches('[data-rt-preserve]')){c.state.profile=H.normalize({...c.state.profile,preserve_geometry:e.target.checked});c.state.dirty=true;schedule();return;}
      if(e.target.matches('[data-rt-shoes]')){
        if(e.target.checked&&['l','r'].some(s=>!c.state.roles[s+'_foot']||!c.state.roles[s+'_shin']||c.state.roles[s+'_foot']===c.state.roles[s+'_shin'])){e.target.checked=false;ui.status('Assign distinct left/right shin and foot bones in What is what before setting shoe boundaries.');return;}
        const p={...c.state.profile};if(e.target.checked)p.shoe_tops={l:.15,r:.15};else delete p.shoe_tops;c.state.profile=H.normalize(p);c.state.dirty=true;schedule();return;}
      if (e.target.matches("[data-rt-tpose]")) { c.setTpose(e.target.checked); return; }
      if (e.target.matches('[data-rt="slot"]')) c.setSlot(e.target.value).then(() => { refit(); schedule(); }).catch(err => ui.status("✗ " + err.message));
    });
    el.addEventListener("click", async e => {
      const history=e.target.closest('[data-rt-fit-job]');
      if(history){try{
        if(!window.GBoxDecimationReview)throw Error('Reload gBox to open saved mesh comparisons.');
        await window.GBoxDecimationReview.open(history.dataset.rtFitJob,history.dataset.rtFitModel,
          {document:doc,api:io.api,assetUrl:io.url,loadViewer:()=>import(io.url('/viz/character-model.js'))});
      }catch(err){ui.status(err.message);}return;}
      const mode = e.target.closest("[data-rt-mode]"); if (mode) { c.setMode(mode.dataset.rtMode); return; }
      const pick = e.target.closest("[data-rt-joint-pick]"); if (pick) { c.selectJoint(pick.dataset.rtJointPick); return; }
      const arm = e.target.closest("[data-rt-arm]"); if (arm) { c.arm(arm.dataset.rtArm); schedule(); return; }
      const part = e.target.closest("[data-rt-part]"); if (part) { c.selectPart(part.dataset.rtPart); return; }
      const go = e.target.closest("[data-rt-go]"); if (!go) return;
      const what = go.dataset.rtGo;
      try {
        if(what==='workspace'){
          if(!window.GBoxDecimationReview?.workspace)throw Error('Blender workspace control is unavailable; reload gBox.');
          const selector=q('[data-rt-topology]'),mode=selector.value;go.disabled=true;selector.disabled=true;
          try{await window.GBoxDecimationReview.workspace({character:c.state.slug,...(mode!=='none'?{mode}:{})},{api:io.api,assetUrl:io.url},q('[data-rt-workspace-status]'),mode==='none'?'mesh_workspace':'hops_workspace');}finally{go.disabled=false;selector.disabled=false;}return;
        }
        if (what === "close") { if (c.state.dirty && io.confirm && !io.confirm("Close without saving the retarget changes?")) return; dispose(); return; }
        if(what === "shape-reset"){const profile={...c.state.profile};delete profile.lattice;c.state.profile=H.normalize(profile);c.state.dirty=true;schedule();return;}
        if (what === "guess") { c.guess(); refit(); schedule(); return; }
        if (what === "part-reset") { c.resetPart(go.dataset.role); schedule(); return; }
        if (what === "joint-reset") { c.resetJoint(go.dataset.role); schedule(); return; }
        if (what === "save") await c.save("slot");
        if (what === "save-all") await c.save("game");
        if (what === "save-rebuild") await c.saveAndRebuild();
        if (what === "reset") { await c.reset("slot"); refit(); schedule(); }
        if (io.onSaved && /save/.test(what)) io.onSaved(c.state);
      } catch (err) { ui.status("✗ " + String(err.message || err).slice(0, 300)); }
    });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => schedule()) : null;
    function dispose() {
      dead = true;textureRequest++;textures?.dispose();photos?.dispose(); if (ro) ro.disconnect();
      for (const v of Object.values(views)) if (v && v.renderer) {
        v.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach(m => m.dispose()); });
        v.renderer.dispose();
      }
      disposeTextureCandidate();
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
      // target: the slot's own skeleton as its last build loaded it (fit goals), else the slot's stock model in the
      // collection, else a standard skeleton at the game's proportions
      const ref = c.state.reference, goal = c.state.goals;
      tPos = H.standardSkeleton(1.7); tGround = 0;
      let tname = ref ? ref.name : "standard skeleton";
      if (goal && goal.target.hip && goal.target.head) {
        const Rg = H.facing(goal.target);
        tPos = Object.fromEntries(Object.entries(goal.target).map(([r, p]) => [r, H.rotate(Rg, p)]));
        tGround = goal.target_ground != null && Rg[1][1] === 1 ? goal.target_ground : Math.min(...Object.values(tPos).map(p => p[1]));
        tname = `${c.state.slot} skeleton (as the last build loaded it)`;
      }
      q('[data-rt="target-name"]').textContent = tname;
      if (THREE && ref && ref.model_url) {
        try {
          const g = await load(ref.model_url); if (dead) return;
          target = readModel(THREE, g);
          const raw = rolePositions(target, ref.roles, I), Rt = H.facing(raw);
          const pos = rolePositions(target, ref.roles, Rt);
          if (pos.hip && pos.head) {
            let gmin = Infinity; for (const m of target.meshes) for (let i = 0; i < m.pos.length; i += 3) gmin = Math.min(gmin, H.rotate(Rt, [m.pos[i], m.pos[i + 1], m.pos[i + 2]])[1]);
            gmin = Number.isFinite(gmin) ? gmin : 0;
            let M = Rt.map(r => r.slice()), t = [0, 0, 0];
            if (goal) {                                       // the stock model brought to the slot's own skeleton
              const bf = H.baseFit(pos, gmin, tPos, tGround); M = M.map(r => r.map(x => x * bf.s)); t = bf.t;
            } else { tPos = pos; tGround = gmin; }
            refHolder = new THREE.Group(); refHolder.add(g.scene);
            refHolder.matrixAutoUpdate = false; refHolder.matrix.set(...M[0], t[0], ...M[1], t[1], ...M[2], t[2], 0, 0, 0, 1); refHolder.matrixWorldNeedsUpdate = true;
            g.scene.traverse(o => { if (o.isMesh) { o.material = new THREE.MeshStandardMaterial({ color: 0x5b6472, transparent: true, opacity: 0.35, depthWrite: false }); } });
            views.target.group.add(refHolder);
          }
        } catch (err) { ui.status("Stock model unavailable (" + err.message + "); showing " + (goal ? "the slot's skeleton" : "a standard skeleton")); }
      }
      if (THREE && c.state.view && c.state.view.model_url) {
        try {
          const g = await load(c.state.view.model_url); if (dead) return;
          donor = readModel(THREE, g);
          c.setBones(donor.bones.map(b => b.name));
          donorScene = g.scene; views.donor.group.add(g.scene);
          for (const m of donor.meshes) {
            const geo = new THREE.BufferGeometry(), attr = new THREE.BufferAttribute(new Float32Array(m.pos.length), 3);
            geo.setAttribute("position", attr); if (m.index) geo.setIndex(Array.from(m.index));
            if(m.uv)geo.setAttribute("uv",new THREE.BufferAttribute(new Float32Array(m.uv),2));
            const material=m.material?([].concat(m.material)[0]).clone():new THREE.MeshStandardMaterial({color:0x8fe6a8,side:THREE.DoubleSide});
            const mesh = new THREE.Mesh(geo, material);
            views.target.group.add(mesh);
            const pm = { src: m, geo, attr, mesh }; previewMeshes.push(pm);
            const pgeo = new THREE.BufferGeometry(), pattr = new THREE.BufferAttribute(new Float32Array(m.pos.length), 3);
            pgeo.setAttribute("position", pattr); if (m.index) pgeo.setIndex(Array.from(m.index));
            if(m.uv)pgeo.setAttribute('uv',new THREE.BufferAttribute(new Float32Array(m.uv),2));
            const pmesh = new THREE.Mesh(pgeo,m.material?[].concat(m.material)[0].clone():new THREE.MeshStandardMaterial({color:0x8fe6a8,side:THREE.DoubleSide}));
            views.donor.posed.add(pmesh); posedMeshes.push({ src: pm, geo: pgeo, attr: pattr, mesh: pmesh });
          }
          refit();
          if (R) { const d = views.donor.group; d.matrixAutoUpdate = false; d.matrix.set(...R[0], 0, ...R[1], 0, ...R[2], 0, 0, 0, 0, 1); d.matrixWorldNeedsUpdate = true; }
        } catch (err) { ui.status("✗ donor model: " + String(err.message || err).slice(0, 200)); }
      }
      schedule();
    })().catch(err => ui.status("✗ " + String(err.message || err).slice(0, 300)));
    if(opts.build_name){
      const history=q('[data-rt-fit-history]');history.hidden=false;history.textContent='Loading this build\'s recorded fitting...';
      io.api(`/api/builds/${encodeURIComponent(opts.gid)}/${encodeURIComponent(opts.build_name)}/fitting?donor=${encodeURIComponent(opts.slug)}`).then(result=>{
        if(dead)return;
        const rows=(result.jobs||[]).flatMap(job=>job.models.map(model=>({job,model})));
        history.innerHTML='<b>Recorded mesh reduction</b>'+ (rows.length?rows.map(({job,model})=>{
          const counts=model.triangles||{};
          return `<p><button class="act" data-rt-fit-job="${ESC(job.job_id)}" data-rt-fit-model="${ESC(model.key)}">${ESC(model.label)}</button> <span class="mut">${counts.source_triangles??'?'} → ${counts.result_triangles??'?'} triangles${model.comparison_available?'':' (exact pair unavailable)'}</span></p>`;
        }).join(''):'<p class="mut">This build has no matching saved fitting job for this donor. The live retarget preview is an adjustment preview; it does not reconstruct the build\'s historical decimation.</p>');
      }).catch(err=>{if(!dead)history.textContent='Saved fitting history unavailable: '+err.message;});
    }
    return { el, controller: c, dispose, views, previewTexture:showTextureCandidate }; // diagnostics and tests
  }

  const api = { controller, open, rolesHTML, globalsHTML, partHTML, headerHTML, frameHTML, readModel, COLORS, tabsHTML, jointHTML,
    legendHTML, CAPTIONS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxRetargetEditor = api;
})(typeof window !== "undefined" ? window : globalThis);
