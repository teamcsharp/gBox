// Controller maps: which control on the operator's pad drives which console function, per console (2026-10-20).
// Right-click a button (or the stick) on the play view's controller picture -> "Map N64 C-up to…": pick a control, or
// press one, or reset. Saved on the server per console (gbox/padmap.py, /api/controller-maps).
//
// A map is {source: output} over RetroPad names, identity by default - RetroArch's own remap model:
//   source = the physical control, named the way RetroArch's positional autoconfig names it
//            (Xbox A = "b", B = "a", X = "y", Y = "x", RB = "r", LT = "l2", right stick up = "rup")
//   output = the RetroPad input the game gets ("rup" = right analog up = C-up on parallel-n64 / mupen64plus-next)
// Binding a control to a function swaps: the control(s) that had the function take over what the new control did,
// so nothing is ever left without a control.
// Where it applies: streamed games - the page maps the pad before forwarding it (read()); a game in a native RetroArch
// window - the worker writes the core's remap file when the game starts (RetroArch reads remaps at launch only).
(function (root) {
  "use strict";
  // RETRO_DEVICE_ID_JOYPAD_* order, then the stick directions (RetroArch's analog binds)
  const BUTTONS = ["b", "y", "select", "start", "up", "down", "left", "right", "a", "x", "l", "r", "l2", "r2", "l3", "r3"];
  const STICK_DIRS = ["lup", "ldown", "lleft", "lright", "rup", "rdown", "rleft", "rright"];
  // Gamepad API "standard" layout: button index -> source (Xbox A = RetroPad B ...), axes -> [negative, positive]
  const STD_BUTTONS = ["b", "a", "y", "x", "l", "r", "l2", "r2", "select", "start", "l3", "r3", "up", "down", "left", "right"];
  const STD_AXES = [["lleft", "lright"], ["lup", "ldown"], ["rleft", "rright"], ["rup", "rdown"]];
  const GROUPS = [["face", "Face buttons"], ["shoulder", "Bumpers and triggers"], ["dpad", "D-pad"],
                  ["lstick", "Left stick"], ["rstick", "Right stick"], ["other", "Other"]];
  const S = (id, label, name, group) => ({ id, label, name, group });
  const SOURCES = [
    S("b", "A", "A", "face"), S("a", "B", "B", "face"), S("y", "X", "X", "face"), S("x", "Y", "Y", "face"),
    S("l", "LB", "LB", "shoulder"), S("r", "RB", "RB", "shoulder"), S("l2", "LT", "LT", "shoulder"), S("r2", "RT", "RT", "shoulder"),
    S("up", "↑", "D-pad up", "dpad"), S("down", "↓", "D-pad down", "dpad"), S("left", "←", "D-pad left", "dpad"), S("right", "→", "D-pad right", "dpad"),
    S("lup", "↑", "Left stick up", "lstick"), S("ldown", "↓", "Left stick down", "lstick"),
    S("lleft", "←", "Left stick left", "lstick"), S("lright", "→", "Left stick right", "lstick"),
    S("rup", "↑", "Right stick up", "rstick"), S("rdown", "↓", "Right stick down", "rstick"),
    S("rleft", "←", "Right stick left", "rstick"), S("rright", "→", "Right stick right", "rstick"),
    S("select", "View", "View", "other"), S("start", "Menu", "Menu", "other"), S("l3", "LS click", "Left stick click", "other"),
    S("r3", "RS click", "Right stick click", "other"),
  ];
  const SOURCE = Object.fromEntries(SOURCES.map(s => [s.id, s]));
  // whole groups of controls, in up / down / left / right order (a function group binds to one of these at once)
  const PHYS = [{ id: "lstick", label: "Left stick", srcs: ["lup", "ldown", "lleft", "lright"] },
                { id: "rstick", label: "Right stick", srcs: ["rup", "rdown", "rleft", "rright"] },
                { id: "dpad", label: "D-pad", srcs: ["up", "down", "left", "right"] }];
  const F = (id, label, out) => ({ id, label, out });
  // What each console does with each RetroPad input. N64: parallel-n64 / mupen64plus-next standard layout (gBox pins it:
  // gbox/adapters.py N64_INPUT_OPTS) - A = RetroPad B, B = Y, Z = L2, C buttons = right analog, stick = left analog,
  // R2 held = "C buttons mode" (RetroPad A / X become C-right / C-up then).
  const PROFILES = {
    n64: {
      name: "Nintendo 64", short: "N64", sticks: true,
      functions: [F("a", "A", "b"), F("b", "B", "y"), F("z", "Z", "l2"), F("start", "Start", "start"), F("l", "L", "l"), F("r", "R", "r"),
                  F("cup", "C-up", "rup"), F("cdown", "C-down", "rdown"), F("cleft", "C-left", "rleft"), F("cright", "C-right", "rright"),
                  F("sup", "Stick up", "lup"), F("sdown", "Stick down", "ldown"), F("sleft", "Stick left", "lleft"), F("sright", "Stick right", "lright"),
                  F("dup", "D-pad up", "up"), F("ddown", "D-pad down", "down"), F("dleft", "D-pad left", "left"), F("dright", "D-pad right", "right"),
                  F("cmode", "C mode (hold)", "r2")],
      groups: [{ id: "stick", label: "Stick", fns: ["sup", "sdown", "sleft", "sright"] },
               { id: "c", label: "C buttons", fns: ["cup", "cdown", "cleft", "cright"] },
               { id: "dpad", label: "D-pad", fns: ["dup", "ddown", "dleft", "dright"] }],
      extra: { a: "C-right (C mode)", x: "C-up (C mode)" },
    },
  };
  const has = (o, k) => !!o && Object.prototype.hasOwnProperty.call(o, k);
  const norm = p => String(p || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  function family(platform) {                   // the key a map is saved under (gbox/padmap.py family)
    const k = norm(platform);
    return ({ n64: "n64", n64dd: "n64", nintendo64: "n64" })[k] || (k.includes("nintendo64") ? "n64" : k);
  }
  function profile(platform) {
    const fam = family(platform), p = PROFILES[fam];
    if (p) return { fam, ...p };
    return { fam, name: String(platform || "this console"), short: "", sticks: false, functions: [], groups: [], extra: {}, generic: true };
  }
  // controls this console's map can move (and the inputs they can drive: the same names)
  const ids = prof => (prof && prof.sticks ? SOURCES.map(s => s.id) : SOURCES.map(s => s.id).filter(s => BUTTONS.includes(s)));
  const effective = (map, src) => (has(map, src) ? map[src] : src);
  function clean(prof, map) {
    const ok = new Set(ids(prof)), out = {};
    for (const [k, v] of Object.entries(map || {})) if (ok.has(k) && ok.has(v) && k !== v) out[k] = v;
    return out;
  }
  const controlsFor = (prof, map, out) => ids(prof).filter(s => effective(map, s) === out);
  // console functions no control drives now
  const unbound = (prof, map) => prof.functions.filter(f => !controlsFor(prof, map, f.out).length);
  // `src` now drives `out`. Buttons that drove `out` take over what `src` drove (a swap). Stick directions that drove
  // it keep it too, unless `whole` (a whole stick or the d-pad moving at once): in a native window RetroArch's remap can
  // only move a stick axis as a whole - a direction remapped alone silences its opposite (input_state_device resets
  // the axis, and the poll loop skips the identity half) - so a single bind never moves half an axis away.
  function bind(prof, map, out, src, { whole = false } = {}) {
    const all = ids(prof), next = clean(prof, map);
    if (!all.includes(src) || !all.includes(out)) return { map: next, moved: [], previous: null, lost: [] };
    const previous = effective(next, src), moved = [];
    if (previous !== out) {
      for (const s of all) if (s !== src && effective(next, s) === out && (whole || !STICK_DIRS.includes(s))) {
        next[s] = previous; moved.push({ source: s, output: previous });
      }
      next[src] = out;
    }
    const m = clean(prof, next);
    const lost = previous !== out && matters(prof, previous) && !controlsFor(prof, m, previous).length ? [previous] : [];
    return { map: m, moved, previous, lost };                // lost: a console function no control does now
  }
  const matters = (prof, out) => prof.generic || !!prof.functions.find(f => f.out === out);
  function bindGroup(prof, map, outs, srcs) {
    let m = clean(prof, map); const moved = [];
    outs.forEach((o, i) => { const r = bind(prof, m, o, srcs[i], { whole: true }); m = r.map; moved.push(...r.moved); });
    return { map: m, moved, lost: [...new Set(outs.concat(srcs).filter(o => matters(prof, o) && !controlsFor(prof, m, o).length))] };
  }
  // `out` back to its default: every control involved with it drives its own input again
  function reset(prof, map, out) {
    const next = clean(prof, map);
    for (const s of ids(prof)) if (s === out || effective(next, s) === out) delete next[s];
    const m = clean(prof, next);
    return { map: m, moved: [], lost: [] };
  }
  // stick directions a native RetroArch window can't keep: the opposite of a direction remapped alone
  const AXES = [["lup", "ldown"], ["lleft", "lright"], ["rup", "rdown"], ["rleft", "rright"]];
  function splitAxes(prof, map) {
    if (!prof.sticks) return [];
    const m = clean(prof, map), out = [];
    for (const [a, b] of AXES) if (has(m, a) !== has(m, b)) out.push(has(m, a) ? b : a);
    return out;
  }
  const outputs = (prof, map, held) => new Set([...held].map(s => effective(map, s)).filter(Boolean));
  // physical controls held: buttons through the pad's own map (index -> RetroPad name), sticks as directions
  function sources(gp, { buttons = STD_BUTTONS, sticks = true, threshold = 0.5 } = {}) {
    const out = new Set();
    ((gp && gp.buttons) || []).forEach((b, i) => { const k = buttons[i]; if (k && b && (b.pressed || b.value > 0.5)) out.add(k); });
    if (sticks) STD_AXES.forEach(([neg, pos], i) => {
      const v = +(((gp && gp.axes) || [])[i]) || 0;
      if (v < -threshold) out.add(neg); if (v > threshold) out.add(pos);
    });
    return out;
  }
  // Player 1's pad as the game receives it: keys = what a streamed game is sent, held = what the controller picture
  // lights, stick / rstick = the game's sticks (for the picture's knob).
  function read(gp, cmap, prof, map, { stickAsDpad = true, deadzone = 0.12 } = {}) {
    map = clean(prof, map);
    const ax = i => { const v = +(((gp && gp.axes) || [])[i]) || 0; return Math.abs(v) > deadzone ? Math.max(-1, Math.min(1, v)) : 0; };
    if (prof.sticks) {
      const src = sources(gp, { buttons: cmap || STD_BUTTONS, sticks: true }), keys = outputs(prof, map, src), strength = {};
      const mag = s => {
        const i = STD_AXES.findIndex(p => p.includes(s));
        if (i < 0) return src.has(s) ? 1 : 0;
        return STD_AXES[i][0] === s ? Math.max(0, -ax(i)) : Math.max(0, ax(i));
      };
      for (const s of ids(prof)) {                 // each direction's strength: from the stick or button that drives it
        const o = effective(map, s), m = mag(s);
        if (m && STICK_DIRS.includes(o)) strength[o] = Math.max(strength[o] || 0, m);
      }
      const vec = p => ({ x: (strength[p + "right"] || 0) - (strength[p + "left"] || 0), y: (strength[p + "down"] || 0) - (strength[p + "up"] || 0) });
      return { keys, held: new Set(keys), stick: vec("l"), rstick: vec("r") };
    }
    // other consoles: the buttons through the map; the left stick doubles as the d-pad (the Controllers page switch)
    const keys = outputs(prof, map, sources(gp, { buttons: cmap || STD_BUTTONS, sticks: false }));
    const a = (gp && gp.axes) || [];
    if (stickAsDpad) { if (a[0] < -0.5) keys.add("left"); if (a[0] > 0.5) keys.add("right"); if (a[1] < -0.5) keys.add("up"); if (a[1] > 0.5) keys.add("down"); }
    const held = new Set(keys);
    for (const s of sources(gp, { buttons: [], sticks: true })) held.add(s);        // the picture shows both sticks
    return { keys, held, stick: { x: ax(0), y: ax(1) }, rstick: { x: ax(2), y: ax(3) } };
  }
  // "Press a control": everything is let go first, then the first control pressed (fixed order when two start together)
  function captureStep(st, held, prof) {
    const all = ids(prof), now = all.filter(s => held.has(s));
    if (!st.armed) { if (!now.length) st.armed = true; return null; }
    return now[0] || null;
  }
  const fnFor = (prof, out) => prof.functions.find(f => f.out === out) || null;
  const groupOf = (prof, fnId) => prof.groups.find(g => g.fns.includes(fnId)) || null;
  function describe(prof, out, labels) {           // what an input does on this console
    const f = fnFor(prof, out);
    if (f) return f.label;
    if (has(prof.extra, out)) return prof.extra[out];
    if (!prof.generic) return "—";                 // a console with its own functions: anything else does nothing
    return labels && has(labels, out) ? pretty(labels[out]) : (out || "").toUpperCase();
  }
  // which whole group of controls drives a function group now (null when it's spread over several)
  function physOf(prof, map, group) {
    const outs = group.fns.map(id => prof.functions.find(f => f.id === id).out);
    return PHYS.find(p => p.srcs.every((s, i) => effective(map, s) === outs[i])) || null;
  }
  function summary(prof, map, labels) {          // the changed controls, for the Controllers page
    const m = clean(prof, map);
    return Object.keys(m).map(s => ({ source: s, name: (SOURCE[s] || { name: s }).name, output: m[s], does: describe(prof, m[s], labels) }));
  }
  // the right-clicked part of the controller picture -> {fn} or {group} of this console, or {error}
  function target(prof, part, labels) {
    const keys = (part && part.keys) || [], first = keys[0] || "";
    if (prof.sticks) {
      if (part && part.stick) {
        const g = prof.groups.find(gr => gr.fns.some(id => keys.includes(prof.functions.find(f => f.id === id).out)));
        return g ? { group: g } : { error: "This stick isn't one of the console's controls." };
      }
      const f = fnFor(prof, first);
      return f ? { fn: f } : { error: `${prof.name} has no function on that part.` };
    }
    if (part && part.stick) return { error: `Stick mapping is available for Nintendo 64 so far. Buttons of the ${prof.name} pad map here.` };
    if (!BUTTONS.includes(first)) return { error: "That part has no button gBox can map." };
    return { fn: { id: first, label: pretty((part && part.label) || (labels && labels[first]) || first), out: first } };
  }
  // a console button name for people: "a" -> "A", "triangle" -> "Triangle"
  const pretty = s => { s = String(s || "").trim(); return s.length <= 2 ? s.toUpperCase() : s[0].toUpperCase() + s.slice(1); };

  // ---------------------------------------------------------------- the dialog ----------------------------------------
  const CSS = `#padmapdlg{position:fixed;z-index:120;width:384px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);overflow:auto;
  background:var(--bg,#16171c);color:var(--fg,#e8e8ee);border:1px solid var(--line,#333);border-radius:8px;padding:10px;box-sizing:border-box;
  box-shadow:0 10px 30px #000a;font-size:12px;line-height:1.35}
#padmapdlg .pm-top{display:flex;align-items:center;gap:6px}#padmapdlg .pm-top b{flex:1;font-size:13px}
#padmapdlg .pm-x{background:none;border:0;color:inherit;cursor:pointer;font-size:15px;padding:0 4px}
#padmapdlg .pm-h{margin:8px 0 3px;color:var(--mut,#9a9aa6);font-size:11px}
#padmapdlg .pm-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}
#padmapdlg .pm-src{display:flex;flex-direction:column;align-items:center;gap:1px;padding:3px 2px;min-width:0;font-size:11px;line-height:1.2}
#padmapdlg .pm-src i{font-style:normal;color:var(--mut,#9a9aa6);font-size:10px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#padmapdlg .pm-src.on{outline:2px solid var(--acc,#7c96ff);outline-offset:-1px}
#padmapdlg .pm-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin-top:6px}
#padmapdlg .pm-st{margin-top:6px;min-height:16px;color:var(--mut,#9a9aa6)}#padmapdlg .pm-st.bad{color:var(--bad,#e0453a)}
#padmapdlg .pm-note{margin-top:8px;color:var(--mut,#9a9aa6);font-size:11px}
#padmapdlg .pm-warn{margin-top:6px;color:var(--warn,#f5c542);font-size:11px}
#padmapdlg .pm-cap.on{border-color:var(--acc,#7c96ff);color:var(--acc,#7c96ff)}`;
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let open = null;
  // o: {x, y, platform, name, part: {keys, label, stick}, map, labels, save(map) -> Promise<map>, read() -> {gp, map}|null,
  //     capturing(on), note, retroarchWindow (the game reads the pad in its own RetroArch window: warn about half
  //     axes), apply: {label, run(say) -> Promise}|null}
  function dialog(o) {
    const doc = root.document;
    if (!doc) return null;
    if (open) open.close();
    if (!doc.getElementById("padmap-css")) { const s = doc.createElement("style"); s.id = "padmap-css"; s.textContent = CSS; doc.head.appendChild(s); }
    const prof = profile(o.platform);
    if (prof.generic && o.name) prof.name = o.name;          // the picture's own name ("Super Nintendo")
    const t = target(prof, o.part, o.labels);
    const st = { map: clean(prof, o.map), status: "", bad: false, cap: null, busy: false };
    const fn = t.fn || null, group = t.group || (fn ? groupOf(prof, fn.id) : null);
    const what = fn ? fn.label : group ? group.label : (o.part && o.part.label) || "this";
    const title = `Map ${prof.short ? prof.short + " " : ""}${what} to…`;
    const el = doc.createElement("div");
    el.id = "padmapdlg"; el.tabIndex = -1;
    el.setAttribute("role", "dialog");                 // the desktop shell cuts [role=dialog] out of a docked game window
    el.setAttribute("aria-label", title);
    const say = (text, bad) => { st.status = text; st.bad = !!bad; const s = el.querySelector(".pm-st"); if (s) { s.textContent = text; s.className = "pm-st" + (bad ? " bad" : ""); } };
    const outs = g => g.fns.map(id => prof.functions.find(f => f.id === id).out);
    function render() {
      const parts = [`<div class="pm-top"><b>${esc(title)}</b><button class="pm-x" data-x aria-label="Close">×</button></div>`];
      if (t.error) parts.push(`<p class="pm-note">${esc(t.error)}</p>`);
      else {
        if (fn) {
          const now = controlsFor(prof, st.map, fn.out).map(s => SOURCE[s].name);
          parts.push(`<div>Now: <b>${esc(now.join(", ") || "nothing")}</b></div>`);
        } else {
          const p = physOf(prof, st.map, group);
          parts.push(`<div>Now: <b>${esc(p ? p.label : group.fns.map(id => SOURCE[controlsFor(prof, st.map, prof.functions.find(f => f.id === id).out)[0]]?.name || "—").join(" / "))}</b></div>`);
        }
        parts.push(`<div class="pm-row"><button class="act pm-cap${st.cap ? " on" : ""}" data-cap>${st.cap ? "Listening… (click to stop)" : (fn ? "Press a control to bind" : "Move a stick or press the D-pad")}</button></div>`);
        if (group) {
          const cur = physOf(prof, st.map, group);
          parts.push(`<div class="pm-h">${fn ? "All " + esc(group.label) : "Whole " + esc(group.label.toLowerCase())}</div><div class="pm-row">` +
            PHYS.map(p => `<button class="act${cur && cur.id === p.id ? " pri" : ""}" data-grp="${p.id}" aria-pressed="${cur && cur.id === p.id}">${esc(p.label)}</button>`).join("") + "</div>");
        }
        if (fn) {
          const all = ids(prof);
          for (const [gid, glabel] of GROUPS) {
            const list = SOURCES.filter(s => s.group === gid && all.includes(s.id));
            if (!list.length) continue;
            parts.push(`<div class="pm-h">${esc(glabel)}</div><div class="pm-grid">` + list.map(s => {
              const on = effective(st.map, s.id) === fn.out, does = describe(prof, effective(st.map, s.id), o.labels);
              return `<button class="act pm-src${on ? " on" : ""}" data-src="${s.id}" aria-pressed="${on}" title="${esc(s.name)} → ${esc(does)}"><b>${esc(s.label)}</b><i>${esc(does)}</i></button>`;
            }).join("") + "</div>");
          }
        }
        parts.push(`<div class="pm-row"><button class="act" data-reset>Reset ${esc(what)}</button><button class="act" data-resetall>Reset all ${esc(prof.short || prof.name)} controls</button>` +
          (o.apply ? `<button class="act pri" data-apply>${esc(o.apply.label)}</button>` : "") + "</div>");
      }
      parts.push(`<div class="pm-st${st.bad ? " bad" : ""}" role="status">${esc(st.status)}</div>`);
      if (!t.error) {
        const none = unbound(prof, st.map).filter(f => f.id !== "cmode");
        if (none.length) parts.push(`<div class="pm-warn">No control: ${esc(none.map(f => f.label).join(", "))}. Right-click it on the picture to give it one.</div>`);
        const dead = o.retroarchWindow ? splitAxes(prof, st.map) : [];
        if (dead.length) parts.push(`<div class="pm-warn">In this RetroArch window a stick axis only moves as a whole: ${esc(dead.map(s => SOURCE[s].name).join(", "))} does nothing while its opposite direction is mapped alone. Map the whole stick instead.</div>`);
      }
      if (o.note) parts.push(`<div class="pm-note">${esc(o.note)}</div>`);
      el.innerHTML = parts.join("");
    }
    async function commit(next, msg) {
      const prev = st.map;
      st.map = clean(prof, next); render(); say(msg + " · saving…");
      try {
        const saved = await o.save(st.map);
        if (saved && typeof saved === "object") st.map = clean(prof, saved);
        render(); say(msg + " · saved");
      } catch (e) { st.map = prev; render(); say("Not saved: " + ((e && e.message) || e), true); }
    }
    const moveText = moved => moved.length ? "; " + moved.map(m => `${SOURCE[m.source].name} → ${describe(prof, m.output, o.labels)}`).join(", ") : "";
    function bindSrc(src) {
      if (!fn) return;
      const r = bind(prof, st.map, fn.out, src);
      const also = controlsFor(prof, r.map, fn.out).filter(s => s !== src).map(s => SOURCE[s].name);
      commit(r.map, `${SOURCE[src].name} → ${fn.label}${also.length ? " (" + also.join(", ") + " too)" : ""}${moveText(r.moved)}`);
    }
    function bindPhys(pid) {
      const p = PHYS.find(x => x.id === pid);
      if (!p || !group) return;
      const r = bindGroup(prof, st.map, outs(group), p.srcs);
      commit(r.map, `${p.label} → ${group.label}`);
    }
    function stopCapture(text) {
      if (!st.cap) return;
      root.cancelAnimationFrame && root.cancelAnimationFrame(st.cap.raf);
      clearTimeout(st.cap.timer); st.cap = null;
      try { o.capturing && o.capturing(false); } catch {}
      render(); if (text) say(text);
    }
    function startCapture() {
      st.cap = { armed: false, raf: 0, timer: setTimeout(() => stopCapture("Nothing was pressed. Try again."), 10000) };
      try { o.capturing && o.capturing(true); } catch {}
      render(); say(fn ? "Press a button, pull a trigger or push a stick…" : "Move a stick or press the D-pad…");
      const tick = () => {
        if (!st.cap) return;
        let r = null;
        try { r = o.read && o.read(); } catch {}
        if (!r || !r.gp) say("No controller seen yet: press any button on it once.");
        else {
          const held = sources(r.gp, { buttons: r.map || STD_BUTTONS, sticks: !!prof.sticks, threshold: 0.6 });
          const got = captureStep(st.cap, held, prof);
          if (got) {
            if (fn) { stopCapture(); bindSrc(got); return; }
            const p = PHYS.find(x => x.srcs.includes(got));
            if (p) { stopCapture(); bindPhys(p.id); return; }
            say(`${SOURCE[got].name} is a button: move a stick or press the D-pad for the whole ${group.label.toLowerCase()}.`);
            st.cap.armed = false;
          }
        }
        st.cap.raf = root.requestAnimationFrame ? root.requestAnimationFrame(tick) : setTimeout(tick, 16);
      };
      tick();
    }
    el.addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      e.stopPropagation();
      if (b.hasAttribute("data-x")) return dlg.close();
      if (b.hasAttribute("data-cap")) return st.cap ? stopCapture("Stopped listening.") : startCapture();
      stopCapture();
      if (b.dataset.src) return bindSrc(b.dataset.src);
      if (b.dataset.grp) return bindPhys(b.dataset.grp);
      if (b.hasAttribute("data-reset")) {
        if (fn) { const r = reset(prof, st.map, fn.out); return commit(r.map, `${fn.label} is back on ${SOURCE[fn.out] ? SOURCE[fn.out].name : fn.out}`); }
        let m = st.map;
        for (const out of outs(group)) m = reset(prof, m, out).map;
        return commit(m, `${group.label} back to default`);
      }
      if (b.hasAttribute("data-resetall")) return commit({}, `All ${prof.short || prof.name} controls back to default`);
      if (b.hasAttribute("data-apply") && o.apply && !st.busy) {
        st.busy = true; b.disabled = true;
        Promise.resolve().then(() => o.apply.run(text => say(text))).then(() => { st.busy = false; dlg.close(); },
          err => { st.busy = false; b.disabled = false; say(String((err && err.message) || err), true); });
      }
    });
    el.addEventListener("contextmenu", e => { e.preventDefault(); e.stopPropagation(); });
    const onKey = e => { if (e.key === "Escape") dlg.close(); };
    const onDown = e => { if (!el.contains(e.target)) dlg.close(); };
    const dlg = {
      el, state: st,
      close() {
        if (open !== dlg) return;
        open = null; stopCapture();
        doc.removeEventListener("keydown", onKey, true); doc.removeEventListener("pointerdown", onDown, true);
        el.remove();
      },
    };
    render();
    (doc.body || doc.documentElement).appendChild(el);
    const vw = root.innerWidth || 1280, vh = root.innerHeight || 800, r = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 384, height: 400 };
    el.style.left = Math.max(8, Math.min((o.x || 0) + 4, vw - r.width - 8)) + "px";
    el.style.top = Math.max(8, Math.min((o.y || 0) + 4, vh - r.height - 8)) + "px";
    doc.addEventListener("keydown", onKey, true); doc.addEventListener("pointerdown", onDown, true);
    open = dlg;
    try { el.focus({ preventScroll: true }); } catch {}
    return dlg;
  }

  const api = { BUTTONS, STICK_DIRS, STD_BUTTONS, STD_AXES, SOURCES, GROUPS, PHYS, PROFILES, family, profile, ids, effective, clean,
                controlsFor, unbound, bind, bindGroup, reset, splitAxes, outputs, sources, read, captureStep, describe, physOf, summary,
                target, dialog, close: () => open && open.close() };
  root.GBoxPadMap = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
