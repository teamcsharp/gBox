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
  const api = { intersect, guestRect, nativePlacement };
  root.GBoxEmbedGeometry = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis);
