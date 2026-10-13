// Convert measured guest CSS coordinates before positioning native windows.
(function (root) {
  const finite = value => typeof value === "number" && Number.isFinite(value);
  function valid(rect) {
    return rect && [rect.x, rect.y, rect.w, rect.h].every(finite) && rect.w > 0 && rect.h > 0;
  }
  function intersect(rect, bounds) {
    if (!valid(rect) || !valid(bounds)) return null;
    const x = Math.max(rect.x, bounds.x), y = Math.max(rect.y, bounds.y);
    const right = Math.min(rect.x + rect.w, bounds.x + bounds.w);
    const bottom = Math.min(rect.y + rect.h, bounds.y + bounds.h);
    return right > x && bottom > y ? { x, y, w: right - x, h: bottom - y } : null;
  }
  function guestRect(rect, host, viewport) {
    const bounds = { x: host?.left, y: host?.top, w: host?.width, h: host?.height };
    if (!valid(rect) || !valid(bounds)) return null;
    const sx = viewport?.w > 0 ? bounds.w / viewport.w : 1;
    const sy = viewport?.h > 0 ? bounds.h / viewport.h : 1;
    return intersect({ x: bounds.x + rect.x * sx, y: bounds.y + rect.y * sy,
                       w: rect.w * sx, h: rect.h * sy }, bounds);
  }
  function nativePlacement(rect, holes = [], displayScale = 1, pageZoom = 1) {
    if (!valid(rect) || !finite(displayScale) || displayScale <= 0 || !finite(pageZoom) || pageZoom <= 0)
      throw new Error("Invalid native game bounds or scale");
    const scale = displayScale * pageZoom;
    const pixels = r => {
      const x = Math.round(r.x * scale), y = Math.round(r.y * scale);
      return { x, y, w: Math.max(1, Math.round((r.x + r.w) * scale) - x),
                    h: Math.max(1, Math.round((r.y + r.h) * scale) - y) };
    };
    const window = pixels(rect), local = { x: 0, y: 0, w: rect.w, h: rect.h };
    return { op: "move", ...window, holes: holes.map(h => intersect(h, local)).filter(Boolean)
      .map(h => { const r = pixels(h); return [r.x, r.y, r.w, r.h]; }) };
  }
  // Do these DOM mutation records open, close or move something cut out of a docked native game window (#1081)?
  // holes: selector of panels/menus that are cut out; ids named in it count even after their ".on" class is removed
  // (closing). bodyChildren: every direct child of body is a potential pop-up (the shell's popups()). ignore: elements
  // the sync places itself (game bar, corner grips), so following them cannot loop. Self-contained: it is also injected
  // into the embedded gBox view as source text.
  function popupMutation(records, { body, holes = "", ignore = "", bodyChildren = true } = {}) {
    const ids = new Set((holes.match(/#[\w-]+/g) || []).map(s => s.slice(1)));
    const relevant = node => !!node && node.nodeType === 1 && !(ignore && node.closest(ignore)) &&
      ((bodyChildren && node.parentElement === body) || ids.has(node.id) ||
       (!!holes && (node.matches(holes) || !!node.closest(holes) || !!node.querySelector(holes))));
    return records.some(r => r.type === "attributes" ? relevant(r.target)
      : [...r.addedNodes, ...r.removedNodes].some(n => relevant(n) || (bodyChildren && r.target === body && n.nodeType === 1)));
  }
  // The visible part of an overlay window of w x h device px laid over the docked game, minus the app's pop-ups over the
  // game (holes in CSS px relative to the game picture, scaled by zoom), as rectangles for BrowserWindow.setShape. The
  // overlay swap model and the voice visualizer float above the game; without this they covered the app's menus (#1081).
  function shapeMinusHoles(w, h, holes = [], zoom = 1) {
    let shape = [{ x: 0, y: 0, width: w, height: h }];
    for (const o of holes || []) {
      const hx = o.x * zoom, hy = o.y * zoom, hx2 = hx + o.w * zoom, hy2 = hy + o.h * zoom, next = [];
      for (const s of shape) {
        const sx2 = s.x + s.width, sy2 = s.y + s.height;
        if (hx >= sx2 || hx2 <= s.x || hy >= sy2 || hy2 <= s.y) { next.push(s); continue; }
        if (hy > s.y) next.push({ x: s.x, y: s.y, width: s.width, height: hy - s.y });
        if (hy2 < sy2) next.push({ x: s.x, y: hy2, width: s.width, height: sy2 - hy2 });
        const my = Math.max(s.y, hy), my2 = Math.min(sy2, hy2);
        if (hx > s.x) next.push({ x: s.x, y: my, width: hx - s.x, height: my2 - my });
        if (hx2 < sx2) next.push({ x: hx2, y: my, width: sx2 - hx2, height: my2 - my });
      }
      shape = next;
    }
    return shape.map(s => ({ x: Math.round(s.x), y: Math.round(s.y), width: Math.max(1, Math.round(s.width)), height: Math.max(1, Math.round(s.height)) }));
  }
  const api = { intersect, guestRect, nativePlacement, popupMutation, shapeMinusHoles };
  root.GBoxEmbedGeometry = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
