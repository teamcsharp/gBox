// Dock (#262): the panels that float over the game (chat, tasks, talk, Other PC, items, inventory, equip, audit, details,
// inspector) can be dragged by their header onto the sidebar, where each becomes a collapsible dock item and the game gets
// its space back. A dock item's header opens or collapses it, dragging the header out of the sidebar floats it again, and
// its arrow button sends it back to where it floated. The layout (which panels are docked, open or collapsed) is remembered
// in localStorage.gbox_dock; panels that are created later (items, inventory, inspector) dock themselves when they appear.
window.GBoxDock = (function () {
  const PANELS = [
    { sel: "#chatpanel", handle: "#chathead", title: "Chat", key: "chat", opener: "#sb-chat" },
    { sel: "#taskpanel", handle: "#taskpanel .th", title: "Tasks", key: "tasks2", opener: "#tb-tasks" },
    { sel: "#live", handle: "#live .hd", title: "Talk", key: "talk" },
    { sel: "#remote-pip", handle: "#remote-pip .rp-head", title: "Other PC" },
    { sel: "#items", handle: "#items .ah", title: "Items", key: "items" },
    { sel: "#reinv", handle: "#reinv .ah", title: "Inventory", key: "reinv" },
    { sel: "#equip", handle: "#equip .ah", title: "Equip", key: "equip" },
    { sel: "#auditpanel", handle: "#auditpanel .ah", title: "Audit", key: "audit", opener: "#sb-audit" },
    { sel: "#svcpanel", handle: "#svcpanel .ah", title: "Details", key: "svc" },
    { sel: "#eyepip", handle: "#eyepip .ah", title: "Inspector", key: "eyepip" },
  ];
  const STORE = "gbox_dock", CONTROLS = "button, input, select, textarea, a, label, option, [contenteditable], [role=button]";
  const CSS = [
    "#dock { display:flex; flex-direction:column; gap:5px; margin:6px 0 4px; min-height:0; overflow:auto; scrollbar-width:thin; }",
    "#dock[hidden] { display:none; }",
    ".app > aside.dock-target { outline:2px dashed var(--acc); outline-offset:-5px; background:#7c96ff14; }",
    ".dock-item { flex:none; border:1px solid var(--line); border-radius:8px; background:var(--card); overflow:hidden; display:flex; flex-direction:column; min-height:0; }",
    ".dock-item .dock-head { display:flex; align-items:center; gap:6px; padding:5px 8px; cursor:grab; user-select:none; font-size:12px; color:var(--fg); }",
    ".dock-item .dock-head:active { cursor:grabbing; }",
    ".dock-item .dock-head b { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; }",
    ".dock-item .dock-caret { width:12px; text-align:center; color:var(--mut); transition:transform .15s; }",
    ".dock-item.collapsed .dock-caret { transform:rotate(-90deg); }",
    ".dock-item .dock-out { border:0; background:none; color:var(--mut); cursor:pointer; padding:0 4px; font:inherit; line-height:1; border-radius:4px; }",
    ".dock-item .dock-out:hover { color:var(--fg); background:#ffffff14; }",
    ".dock-item > .docked { display:flex; flex-direction:column; position:static !important; inset:auto !important; width:auto !important; height:var(--dock-h,380px) !important;" +
      " min-width:0 !important; min-height:0 !important; max-width:none !important; max-height:none !important; margin:0 !important; transform:none !important; box-shadow:none !important;" +
      " border:0 !important; border-top:1px solid var(--line) !important; border-radius:0 !important; z-index:auto !important; resize:none !important; opacity:1 !important; }",
    ".dock-item.collapsed > .docked { display:none !important; }",
    ".dock-item > .docked > .gb-rz { display:none !important; }",
    ".dock-item > #chatpanel { display:grid !important; grid-template-columns:minmax(0,1fr) !important; }",
    ".dock-item > #chatpanel:not(.hist) > #chathist { display:none; } .dock-item > #chatpanel.hist > #chatmain { display:none; }",
    ".dock-item > #taskpanel { display:block !important; } .dock-item > #taskpanel .tkv-layout { grid-template-columns:1fr; height:auto; }",
    ".dock-item > #taskpanel .tkv-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }",
    ".dock-item > #remote-pip.minimized { height:42px !important; }",
    "body.dockwide:not(.navc) .app { grid-template-columns:var(--dock-w,370px) minmax(0,1fr); }",
    "body.dockwide:not(.navc) .app.has-assets { grid-template-columns:var(--dock-w,370px) minmax(0,1fr) var(--assets-width,280px); }",
  ].join("\n");
  const D = { doc: null, win: null, aside: null, dock: null, storage: null, floating: null, onLayout: null, docked: new Map(), drag: null, out: null, pending: [] };
  const panel = sel => PANELS.find(p => p.sel === sel);
  const STYLE = ["position", "left", "top", "right", "bottom", "inset", "width", "height", "margin", "box-sizing", "z-index", "transform"];
  const clear = el => { for (const n of STYLE) el.style.removeProperty(n); };

  // is the point inside a visible sidebar box? pure
  function hit(rect, x, y) {
    return !!rect && rect.width > 24 && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }
  function read() {
    try { return JSON.parse(D.storage?.getItem(STORE) || "null") || { items: [], on: {} }; } catch { return { items: [], on: {} }; }
  }
  function save() {
    const items = [...D.docked.keys()], on = {};
    for (const sel of items) on[sel] = D.docked.get(sel).el.classList.contains("on");
    try { D.storage?.setItem(STORE, JSON.stringify({ items, on })); } catch {}
  }
  // collapsed items hide their panel; the sidebar widens while any docked panel is open; the game re-fits
  function layout() {
    let wide = false;
    for (const [, d] of D.docked) { const open = d.el.classList.contains("on"); d.item.classList.toggle("collapsed", !open); wide = wide || open; }
    const body = D.doc.body, was = body.classList.contains("dockwide");
    body.classList.toggle("dockwide", wide);
    D.dock.hidden = !D.docked.size;
    if (was !== wide) D.onLayout?.(wide);
    return wide;
  }
  function dock(sel, open) {
    const p = panel(sel), el = p && D.doc.querySelector(sel);
    if (!el || D.docked.has(sel)) return false;
    if (typeof el.__floatingDestroy === "function") el.__floatingDestroy();
    clear(el);
    const item = D.doc.createElement("div"), head = D.doc.createElement("div"), caret = D.doc.createElement("span"),
          title = D.doc.createElement("b"), out = D.doc.createElement("button");
    item.className = "dock-item"; item.dataset.dock = sel;
    head.className = "dock-head"; head.title = "Click to open or collapse; drag out of the sidebar to float it over the game again";
    caret.className = "dock-caret"; caret.textContent = "▾"; title.textContent = p.title;
    out.className = "dock-out"; out.type = "button"; out.textContent = "↗"; out.title = "Undock: float it over the game again";
    out.setAttribute("aria-label", "Undock " + p.title);
    head.append(caret, title, out); item.append(head, el); D.dock.append(item);
    el.classList.add("docked");
    if (open !== undefined) el.classList.toggle("on", !!open); else if (!el.classList.contains("on")) el.classList.add("on");
    const d = { el, item, head, p };
    D.docked.set(sel, d);
    head.addEventListener("click", e => { if (e.target.closest(".dock-out") || D.out?.moved) return; toggle(sel); });
    out.addEventListener("click", e => { e.stopPropagation(); undock(sel); });
    head.addEventListener("pointerdown", e => {
      if (e.button !== 0 || e.target.closest(".dock-out")) return;
      D.out = { sel, id: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
    });
    if (typeof MutationObserver === "function") {
      d.mo = new MutationObserver(() => { layout(); save(); });
      d.mo.observe(el, { attributes: true, attributeFilter: ["class"] });
    }
    layout(); save();
    return true;
  }
  // the item's header: its opener (chat, tasks, audit) loads the panel the way the status bar does; others just show / hide
  function toggle(sel) {
    const d = D.docked.get(sel); if (!d) return false;
    const opener = d.p.opener && D.doc.querySelector(d.p.opener);
    if (opener) opener.click(); else d.el.classList.toggle("on");
    layout(); save();
    return d.el.classList.contains("on");
  }
  // back over the game: at the pointer when dragged out, else where it floated before
  function undock(sel, at) {
    const d = D.docked.get(sel); if (!d) return false;
    d.mo?.disconnect();
    D.doc.body.append(d.el); d.item.remove(); D.docked.delete(sel);
    d.el.classList.remove("docked"); clear(d.el);
    const x = at ? Math.max(0, at.x - 80) : null, y = at ? Math.max(36, at.y - 14) : null;
    if (d.p.key && at) {
      let prev = {}; try { prev = JSON.parse(D.storage?.getItem("gbox_float_" + d.p.key) || "null") || {}; } catch {}
      try { D.storage?.setItem("gbox_float_" + d.p.key, JSON.stringify({ x, y, w: prev.w, h: prev.h })); } catch {}
    }
    const handle = D.doc.querySelector(d.p.handle);
    if (d.p.key && typeof D.floating === "function" && handle) D.floating(d.el, handle, d.p.key);
    else if (at) { d.el.style.left = x + "px"; d.el.style.top = y + "px"; d.el.style.right = d.el.style.bottom = "auto"; }
    layout(); save();
    return true;
  }
  function restore() {
    const st = read();
    D.pending = [];
    for (const sel of st.items || []) if (panel(sel) && !dock(sel, st.on?.[sel])) D.pending.push({ sel, on: st.on?.[sel] });
  }
  function appeared() {                                       // a lazily created panel the remembered layout wants docked
    if (D.pending.length) D.pending = D.pending.filter(p => !dock(p.sel, p.on));
  }
  function mount(o = {}) {
    D.doc = o.document || document; D.win = o.window || window;
    D.storage = o.storage !== undefined ? o.storage : (() => { try { return D.win.localStorage; } catch { return null; } })();
    D.floating = o.floating || D.win.floating || null; D.onLayout = o.onLayout || null;
    D.aside = o.aside || D.doc.querySelector(".app > aside"); if (!D.aside) return null;
    if (o.css !== false) { const s = D.doc.createElement("style"); s.textContent = CSS; D.doc.head.append(s); }
    D.dock = D.doc.createElement("div"); D.dock.id = "dock"; D.dock.hidden = true;
    const st = D.aside.querySelector(".st"); if (st) st.before(D.dock); else D.aside.append(D.dock);
    D.doc.addEventListener("pointerdown", e => {               // a panel header picked up: watch for a drop on the sidebar
      if (e.button !== 0 || !e.target.closest || e.target.closest(CONTROLS)) return;
      const p = PANELS.find(q => e.target.closest(q.handle)); if (!p || D.docked.has(p.sel)) return;
      D.drag = { sel: p.sel, id: e.pointerId, x: e.clientX, y: e.clientY, moved: false, over: false };
    }, true);
    D.win.addEventListener("pointermove", e => {
      if (D.drag && D.drag.id === e.pointerId) {
        D.drag.moved = D.drag.moved || Math.abs(e.clientX - D.drag.x) + Math.abs(e.clientY - D.drag.y) > 6;
        D.drag.over = D.drag.moved && !D.doc.body.classList.contains("navc") && hit(D.aside.getBoundingClientRect(), e.clientX, e.clientY);
        D.aside.classList.toggle("dock-target", D.drag.over);
      }
      if (D.out && D.out.id === e.pointerId) {
        D.out.moved = D.out.moved || Math.abs(e.clientX - D.out.x) + Math.abs(e.clientY - D.out.y) > 6;
        const r = D.aside.getBoundingClientRect();
        if (D.out.moved && (e.clientX > r.right + 24 || e.clientX < r.left - 24)) { const sel = D.out.sel; D.out = null; undock(sel, { x: e.clientX, y: e.clientY }); }
      }
    });
    const end = e => {
      if (D.drag && (!e || D.drag.id === e.pointerId)) {
        const { sel, over } = D.drag; D.drag = null; D.aside.classList.remove("dock-target");
        if (over && e) dock(sel);
      }
      if (D.out && (!e || D.out.id === e.pointerId)) { const o = D.out; setTimeout(() => { if (D.out === o) D.out = null; }, 0); }
    };
    D.win.addEventListener("pointerup", end); D.win.addEventListener("pointercancel", end); D.win.addEventListener("blur", () => end());
    if (typeof MutationObserver === "function") new MutationObserver(appeared).observe(D.doc.body, { childList: true });
    restore();
    return api;
  }
  const api = { PANELS, mount, dock, undock, toggle, hit, layout, appeared, isDocked: sel => D.docked.has(sel), docked: () => [...D.docked.keys()], state: D };
  return api;
})();
