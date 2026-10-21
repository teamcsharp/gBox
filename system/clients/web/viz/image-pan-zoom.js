// #2799: an image preview (sprite sheet, tile atlas) that zooms around the cursor with the mouse wheel, pans by
// dragging, shows pixels unsmoothed past 1x and resets on double-click. mount(host, src, alt) -> { reset, dispose }.
(function (root) {
  const MIN = 0.1, MAX = 64;
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function zoomAt(view, factor, px, py) {          // keep the image point under (px, py) fixed while scaling
    const scale = clamp(view.scale * factor, MIN, MAX), k = scale / view.scale;
    return { scale, x: px - (px - view.x) * k, y: py - (py - view.y) * k };
  }
  function fit(w, h, iw, ih) {
    const scale = Math.min(w / iw, h / ih) || 1;
    return { scale, x: (w - iw * scale) / 2, y: (h - ih * scale) / 2 };
  }
  function mount(host, src, alt = '') {
    host.innerHTML = '';
    host.style.position = host.style.position || 'relative';
    const box = document.createElement('div');
    box.className = 'pan-zoom';
    box.style.cssText = 'position:relative;width:100%;height:100%;overflow:hidden;cursor:grab;touch-action:none';
    const img = document.createElement('img');
    img.alt = alt; img.draggable = false; img.src = src;
    img.style.cssText = 'position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;max-height:none;user-select:none';
    const hint = document.createElement('span');
    hint.className = 'mut';
    hint.style.cssText = 'position:absolute;right:8px;bottom:6px;font-size:11px;pointer-events:none;background:#0008;padding:1px 6px;border-radius:4px';
    box.append(img, hint); host.append(box);
    let view = { scale: 1, x: 0, y: 0 }, drag = null;
    const apply = () => {
      img.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
      img.style.imageRendering = view.scale >= 1 ? 'pixelated' : 'auto';
      hint.textContent = `${Math.round(view.scale * 100)}% · wheel to zoom · drag to pan · double-click to fit`;
    };
    const reset = () => { if (img.naturalWidth) view = fit(box.clientWidth, box.clientHeight, img.naturalWidth, img.naturalHeight); apply(); };
    img.addEventListener('load', reset);
    const wheel = e => {
      e.preventDefault();
      const r = box.getBoundingClientRect();
      view = zoomAt(view, Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top); apply();
    };
    const down = e => { if (e.button !== 0) return; drag = { x: e.clientX - view.x, y: e.clientY - view.y }; box.setPointerCapture?.(e.pointerId); box.style.cursor = 'grabbing'; };
    const move = e => { if (!drag) return; view = { ...view, x: e.clientX - drag.x, y: e.clientY - drag.y }; apply(); };
    const up = e => { drag = null; box.releasePointerCapture?.(e.pointerId); box.style.cursor = 'grab'; };
    box.addEventListener('wheel', wheel, { passive: false });
    box.addEventListener('pointerdown', down);
    box.addEventListener('pointermove', move);
    box.addEventListener('pointerup', up);
    box.addEventListener('pointercancel', up);
    box.addEventListener('dblclick', reset);
    apply();
    return { reset, img, get view() { return view; },
             dispose() { box.remove(); } };
  }
  const api = { mount, zoomAt, fit, MIN, MAX };
  root.GBoxImagePanZoom = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
