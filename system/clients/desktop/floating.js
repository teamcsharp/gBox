// Shared popup geometry and pointer lifecycle. A removed popup releases its listeners.
window.floating = function (el, handle, key) {
  if (!el || !handle || el.__floatingDestroy) return;
  const abort = new AbortController(), options = { signal: abort.signal };
  let drag = null, shown = false, geometry = null, frame = 0;
  const finite = (value, fallback) => Number.isFinite(value) ? value : fallback;
  const visible = () => el.isConnected && getComputedStyle(el).display !== "none" && (!(el instanceof HTMLDialogElement) || el.open);
  const place = requested => {
    const r = el.getBoundingClientRect(), top = Math.min(36, Math.max(0, innerHeight - 1));
    const maxW = Math.max(1, innerWidth - 8), maxH = Math.max(1, innerHeight - top - 34);
    const w = Math.max(Math.min(320, maxW), Math.min(maxW, finite(requested.w, r.width)));
    const h = Math.max(Math.min(240, maxH), Math.min(maxH, finite(requested.h, r.height)));
    const x = Math.max(0, Math.min(innerWidth - w, finite(requested.x, r.left)));
    const y = Math.max(top, Math.min(innerHeight - 30 - h, finite(requested.y, r.top)));
    geometry = { x, y, w, h };
    for (const [name, value] of Object.entries({ position: "fixed", margin: "0", right: "auto", bottom: "auto", left: x + "px", top: y + "px", width: w + "px", height: h + "px", "box-sizing": "border-box" }))
      el.style.setProperty(name, value, "important");
    if (typeof window.onFloatingMove === "function") window.onFloatingMove();
  };
  const save = () => { if (geometry) try { localStorage.setItem("gbox_float_" + key, JSON.stringify(geometry)); } catch {} };
  try { geometry = JSON.parse(localStorage.getItem("gbox_float_" + key) || "null"); } catch {}
  const raise = () => { window.__floatingZ = Math.max(100, window.__floatingZ || 100) + 1; el.style.setProperty("z-index", String(window.__floatingZ), "important"); };
  const fit = () => {
    frame = 0; const now = visible();
    if (now && !shown) { raise(); place(geometry || {}); }
    shown = now;
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(fit); };
  const changed = new MutationObserver(() => { if (!el.isConnected) el.__floatingDestroy(); else schedule(); });
  changed.observe(el, { attributes: true, attributeFilter: ["class", "open"] });
  const removed = new MutationObserver(() => { if (!el.isConnected) el.__floatingDestroy(); });
  removed.observe(document.body, { childList: true });
  const end = event => {
    if (!drag || (event && event.pointerId !== drag.id)) return;
    const previous = drag; drag = null;
    if (el.hasPointerCapture(previous.id)) el.releasePointerCapture(previous.id);
    if (previous.moved) save();
  };
  const start = (event, side = "") => {
    if (event.button !== 0 || drag) return;
    raise();
    const control = event.target.closest("button,input,textarea,select,a,[contenteditable],[role=button],.ci,.gchip");
    if (!side && control) return;
    const inHeader = handle.contains(event.target);
    if (!side && !inHeader && !event.altKey && event.target.closest("label,canvas,video,img,pre,code,p,li,td,summary,details,.cm,.lc,.slider")) return;
    const r = el.getBoundingClientRect();
    drag = { id: event.pointerId, side, x: event.clientX, y: event.clientY, r, moved: false };
    el.setPointerCapture(event.pointerId);
    if (side || inHeader || event.altKey) event.preventDefault();
    event.stopPropagation();
  };
  el.addEventListener("pointerdown", event => start(event, event.target.closest(".gb-rz")?.dataset.side || ""), options);
  window.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y, r = drag.r, side = drag.side;
    if (!drag.moved && !side && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    if (!side) { place({ x: r.left + dx, y: r.top + dy, w: r.width, h: r.height }); return; }
    let x = r.left, y = r.top, w = r.width, h = r.height;
    const minW = Math.min(320, Math.max(1, innerWidth - 8)), minH = Math.min(240, Math.max(1, innerHeight - 70));
    if (side.includes("e")) w += dx;
    if (side.includes("s")) h += dy;
    if (side.includes("w")) { w = Math.max(minW, r.width - dx); x = r.right - w; }
    if (side.includes("n")) { h = Math.max(minH, r.height - dy); y = r.bottom - h; }
    place({ x, y, w, h });
  }, options);
  // Chromium can lose element capture during a popup repaint. Continue the drag
  // through window events until the actual release/cancel, rather than ending it early.
  for (const name of ["pointerup", "pointercancel"]) window.addEventListener(name, end, options);
  window.addEventListener("blur", () => end(), options);
  handle.classList.add("gb-drag"); handle.title ||= "Drag to move; Alt+drag the popup to move it from anywhere";
  for (const side of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
    const grip = document.createElement("div"); grip.className = "gb-rz gb-rz-" + side; grip.dataset.side = side; grip.setAttribute("aria-hidden", "true"); el.append(grip);
  }
  handle.addEventListener("dblclick", event => {
    if (event.target.closest("button,input,select,textarea")) return;
    geometry = null; try { localStorage.removeItem("gbox_float_" + key); } catch {}
    for (const name of ["left", "top", "right", "bottom", "width", "height", "margin", "position"]) el.style.removeProperty(name);
    if (visible()) place({});
  }, options);
  window.addEventListener("resize", () => { if (visible()) { end(); place(geometry || {}); } }, options);
  el.__floatingDestroy = () => { end(); abort.abort(); changed.disconnect(); removed.disconnect(); if (frame) cancelAnimationFrame(frame); delete el.__floatingDestroy; };
  schedule();
};
