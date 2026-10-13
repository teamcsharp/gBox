// Toasts and floating panels that stay inside the window, below the app's header bar. Shared verbatim by the web shell
// (/viz/toast-stack.js) and the desktop app (../web/viz/toast-stack.js).
//   limits(doc, o)  the box floating things may use: below every visible header bar (o.header: selector, measured, never
//                   hard-coded; o.top(): an extra measured edge such as the embedded page's own header), above every
//                   visible bottom strip (o.footer), inside the window, o.margin px in from each edge.
//   clampBox(b, L)  a box moved and capped so it fits L (pure: the node tests drive it).
//   fit(el, o)      a fixed panel kept inside limits(): its height capped (it scrolls inside) and moved back in when out.
//   mount(doc, o)   the toast stack: one column in the top-right corner under the header, newest first, at most o.max
//                   cards, capped to the room below the header (it scrolls inside), cards that wrap long titles and text,
//                   laid out again on window resize and when a header bar changes height (wraps to a second row).
// The stack element is #gbox-toasts: the desktop app cuts it out of a docked native game window (EMB_HOLES / its guest
// menu list), so a toast never hides behind the game. Its [hidden] while empty, so no empty hole is cut.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxToastStack = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";
  const MARGIN = 8, MIN_ROOM = 96, WIDTH = 360, MAX = 6;
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

  // visible elements matching sel -> their client rects
  function rects(doc, sel) {
    if (!sel || !doc || typeof doc.querySelectorAll !== "function") return [];
    const view = doc.defaultView;
    const out = [];
    for (const el of Array.from(doc.querySelectorAll(sel))) {
      if (view && typeof view.getComputedStyle === "function") {
        const s = view.getComputedStyle(el);
        if (s && (s.display === "none" || s.visibility === "hidden")) continue;
      }
      const r = el.getBoundingClientRect && el.getBoundingClientRect();
      if (r && r.width > 0 && r.height > 0) out.push(r);
    }
    return out;
  }
  function viewSize(doc, o) {
    const view = (doc && doc.defaultView) || o.view || {};
    return { vw: o.vw != null ? o.vw : view.innerWidth || 1280, vh: o.vh != null ? o.vh : view.innerHeight || 800 };
  }
  // {top, bottom, left, right, vw, vh}: header bars are the matches in the upper half of the window, footers the ones in
  // the lower half; a tiny window keeps at least MIN_ROOM px (inside the window always wins over below the header)
  function limits(doc, o = {}) {
    const { vw, vh } = viewSize(doc, o), m = o.margin != null ? o.margin : MARGIN;
    let top = 0, bottom = vh;
    for (const r of rects(doc, o.header)) if (r.top < vh / 2 && r.bottom > 0) top = Math.max(top, Math.min(r.bottom, vh));
    for (const r of rects(doc, o.footer)) if (r.bottom > vh / 2 && r.top < vh) bottom = Math.min(bottom, Math.max(r.top, 0));
    if (typeof o.top === "function") { const t = +o.top() || 0; if (t > top && t < vh) top = t; }
    let L = { top: top + m, bottom: bottom - m, left: m, right: vw - m, vw, vh };
    const room = Math.min(MIN_ROOM, vh - 2 * m);
    if (L.bottom - L.top < room) L = { ...L, top: Math.max(m, L.bottom - room) };
    if (L.bottom - L.top < room) L = { ...L, bottom: Math.min(vh - m, L.top + room) };
    return L;
  }
  // a box {left, top, width, height} moved and capped to fit L -> {left, top, width, height, maxWidth, maxHeight, moved}
  function clampBox(b, L) {
    const maxWidth = Math.max(0, L.right - L.left), maxHeight = Math.max(0, L.bottom - L.top);
    const width = Math.min(b.width, maxWidth), height = Math.min(b.height, maxHeight);
    const left = Math.min(Math.max(b.left, L.left), L.right - width), top = Math.min(Math.max(b.top, L.top), L.bottom - height);
    return { left, top, width, height, maxWidth, maxHeight, moved: Math.abs(left - b.left) > 0.5 || Math.abs(top - b.top) > 0.5 };
  }
  // where the stack goes: the top-right corner of L, o.width wide at most
  function stackLayout(L, o = {}) {
    const width = Math.max(0, Math.min(o.width || WIDTH, L.right - L.left));
    return { top: L.top, right: L.vw - L.right, width, maxHeight: Math.max(0, L.bottom - L.top) };
  }
  // a fixed panel kept inside limits(): o.pinTop puts it right under the header; otherwise it moves only when it is out;
  // o.maxHeight caps it lower than the room left
  function fit(el, o = {}) {
    if (!el || !el.style) return null;
    const L = o.limits || limits(el.ownerDocument || o.doc, o);
    const maxHeight = Math.max(0, Math.min(L.bottom - L.top, o.maxHeight || Infinity)), maxWidth = Math.max(0, L.right - L.left);
    el.style.maxHeight = maxHeight + "px"; el.style.maxWidth = maxWidth + "px";
    if (o.scroll !== false) { el.style.overflowY = "auto"; el.style.overscrollBehavior = "contain"; }
    if (o.pinTop) { el.style.top = L.top + "px"; el.style.bottom = "auto"; }
    const r = el.getBoundingClientRect && el.getBoundingClientRect();
    if (!r || (!r.width && !r.height)) return { limits: L, moved: false };
    const c = clampBox({ left: r.left, top: r.top, width: r.width, height: r.height }, L);
    if (c.moved) {
      if (Math.abs(c.top - r.top) > 0.5) { el.style.top = c.top + "px"; el.style.bottom = "auto"; }
      if (Math.abs(c.left - r.left) > 0.5) { el.style.left = c.left + "px"; el.style.right = "auto"; }
      el.style.transform = "none";
    }
    return { ...c, limits: L };
  }

  const CSS = `#gbox-toasts{position:fixed;box-sizing:border-box;display:flex;flex-direction:column;gap:8px;overflow-y:auto;overflow-x:hidden;
    overscroll-behavior:contain;scrollbar-width:thin;padding:0 2px 8px 0;pointer-events:auto}
  #gbox-toasts[hidden]{display:none}
  #gbox-toasts>.gts-card{flex:none;min-width:0;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere;white-space:normal}
  #gbox-toasts .gts-box{display:flex;gap:8px;align-items:flex-start;padding:9px 10px;background:var(--bg,#16161a);color:var(--fg,#e8e8ee);
    border:1px solid var(--line,#2c2c34);border-radius:10px;box-shadow:0 6px 18px #0009;font:12.5px/1.4 system-ui,sans-serif}
  #gbox-toasts .gts-box.gts-bad{border-color:var(--bad,#ff6b6b)}
  #gbox-toasts .gts-m{flex:1;min-width:0;display:grid;gap:2px}
  #gbox-toasts .gts-t{font-weight:600}#gbox-toasts .gts-x{color:var(--mut,#9a9aa6)}#gbox-toasts .gts-bad .gts-x{color:var(--bad,#ff6b6b)}
  #gbox-toasts .gts-btns{display:flex;gap:4px;flex-wrap:wrap;margin-top:3px}
  #gbox-toasts .gts-btns button{font:inherit;font-size:11.5px;padding:2px 7px;border:1px solid var(--line,#2c2c34);border-radius:4px;
    background:var(--bg,#16161a);color:var(--fg,#e8e8ee);cursor:pointer}
  #gbox-toasts .gts-close{flex:none;background:none;border:0;color:var(--mut,#9a9aa6);cursor:pointer;font-size:13px;line-height:1;padding:1px 2px}
  #gbox-toasts .gts-close:hover{color:var(--fg,#e8e8ee)}`;

  // a text card: {title?, text, actions?: [[label, run]], close}
  function textHTML(t) {
    const acts = (t.actions || []).map((a, i) => `<button type="button" data-gts-act="${i}">${ESC(a[0])}</button>`).join("");
    return `<div class="gts-m">${t.title ? `<b class="gts-t">${ESC(t.title)}</b>` : ""}${t.text != null && t.text !== "" ? `<span class="gts-x">${ESC(t.text)}</span>` : ""}`
      + `${acts ? `<div class="gts-btns">${acts}</div>` : ""}</div>`
      + (t.close === false ? "" : `<button type="button" class="gts-close" data-gts-close title="Dismiss" aria-label="Dismiss">✕</button>`);
  }

  // o = {id?, header, footer, top?(), margin?, width?, max?, zIndex?, setTimeout?, clearTimeout?}
  function mount(doc, o = {}) {
    const view = doc.defaultView || {};
    const later = o.setTimeout || ((fn, ms) => (view.setTimeout || setTimeout)(fn, ms));
    const cancel = o.clearTimeout || (t => (view.clearTimeout || clearTimeout)(t));
    const max = o.max || MAX;
    if (!doc.getElementById("gbox-toasts-css") && doc.head) {
      const s = doc.createElement("style"); s.id = "gbox-toasts-css"; s.textContent = CSS; doc.head.appendChild(s);
    }
    let el = doc.getElementById(o.id || "gbox-toasts");
    if (!el) {
      el = doc.createElement("div"); el.id = o.id || "gbox-toasts";
      el.setAttribute("aria-live", "polite"); el.setAttribute("aria-label", "Notifications");
      (doc.body || doc.documentElement).appendChild(el);
    }
    el.hidden = true;
    el.style.zIndex = String(o.zIndex != null ? o.zIndex : 86);
    const cards = new Map();                // id -> {card, timer, ms, actions}
    let seq = 0, hover = false, ro = null;
    const watched = new Set();
    function watchHeaders() {               // a header bar that wraps to a second row moves the stack down with it
      if (!o.header || typeof view.ResizeObserver !== "function" || typeof doc.querySelectorAll !== "function") return;
      if (!ro) ro = new view.ResizeObserver(() => relayout());
      for (const h of Array.from(doc.querySelectorAll(o.header))) if (!watched.has(h)) { watched.add(h); ro.observe(h); }
    }
    function relayout() {
      const L = limits(doc, o), p = stackLayout(L, o);
      el.style.top = p.top + "px"; el.style.right = p.right + "px"; el.style.width = p.width + "px";
      el.style.maxHeight = p.maxHeight + "px";
      el.hidden = cards.size === 0;
      watchHeaders();
      return { ...p, limits: L };
    }
    function arm(id) {
      const c = cards.get(id); if (!c || !c.ms) return;
      if (c.timer) cancel(c.timer);
      c.timer = later(() => { c.timer = null; if (hover) arm(id); else remove(id); }, hover ? 1500 : c.ms);
    }
    // t = {id?, html? | text, title?, kind?, ms?, actions?, close?, role?} -> the card (newest first, same id replaces)
    function push(t = {}) {
      const id = String(t.id != null ? t.id : "t" + (++seq));
      remove(id, true);
      const card = doc.createElement("div");
      card.className = "gts-card" + (t.html != null ? "" : " gts-box") + (t.kind ? " gts-" + t.kind : "");
      card.setAttribute("data-gts", id); card.setAttribute("role", t.role || "status");
      card.innerHTML = t.html != null ? String(t.html) : textHTML(t);
      if (el.firstChild) el.insertBefore(card, el.firstChild); else el.appendChild(card);
      cards.set(id, { card, timer: null, ms: t.ms || 0, actions: t.actions || [] });
      arm(id);
      const ids = Array.from(cards.keys());          // insertion order: oldest first
      while (cards.size > max) remove(ids.shift(), true);
      relayout();
      el.scrollTop = 0;                              // the newest one is in view
      return card;
    }
    function remove(id, quiet) {
      const c = cards.get(String(id)); if (!c) return false;
      if (c.timer) cancel(c.timer);
      cards.delete(String(id));
      if (c.card.parentNode) c.card.parentNode.removeChild(c.card);
      if (!quiet) relayout(); else el.hidden = cards.size === 0;
      return true;
    }
    function clear() { for (const id of Array.from(cards.keys())) remove(id, true); relayout(); }
    function onClick(e) {
      const t = e.target, card = t && t.closest && t.closest("[data-gts]");
      if (!card) return;
      const id = card.getAttribute("data-gts"), c = cards.get(id);
      if (t.closest("[data-gts-close]")) { remove(id); return; }
      const a = t.closest("[data-gts-act]");
      if (a && c) { const act = c.actions[+a.getAttribute("data-gts-act")]; remove(id); if (act && typeof act[1] === "function") act[1](); }
    }
    const onResize = () => relayout();
    const enter = () => { hover = true; }, leave = () => { hover = false; };
    if (typeof el.addEventListener === "function") {
      el.addEventListener("click", onClick);
      el.addEventListener("mouseenter", enter); el.addEventListener("mouseleave", leave);
    }
    if (typeof view.addEventListener === "function") view.addEventListener("resize", onResize);
    relayout();
    return {
      el, push, remove, clear, relayout,
      has: id => cards.has(String(id)),
      ids: () => Array.from(el.children || []).map(c => c.getAttribute("data-gts")),   // newest first
      get size() { return cards.size; },
      dispose() {
        clear();
        if (ro) ro.disconnect();
        if (typeof view.removeEventListener === "function") view.removeEventListener("resize", onResize);
        if (typeof el.removeEventListener === "function") el.removeEventListener("click", onClick);
        if (el.parentNode) el.parentNode.removeChild(el);
      },
    };
  }

  return { limits, clampBox, stackLayout, fit, mount, textHTML, rects, CSS, MARGIN, WIDTH, MAX };
});
