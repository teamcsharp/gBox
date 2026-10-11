/* Gameplay previews for header session chips. Reads frames; never controls games. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else { root.GBoxSessionHover = api; api.mount(); }
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const overlaps = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x &&
    a.y < b.y + b.height && a.y + a.height > b.y;
  function placement(anchor, viewport, obstacle) {
    const margin = 8, gap = 8;
    const bounds = { x: margin, y: margin,
      width: Math.max(1, viewport.width - 2 * margin), height: Math.max(1, viewport.height - 2 * margin) };
    const fit = (area, preferred) => {
      const width = Math.min(360, area.width), height = Math.min(width * 9 / 16 + 72, area.height);
      return { x: Math.max(area.x, Math.min(area.x + area.width - width, preferred.x)),
        y: Math.max(area.y, Math.min(area.y + area.height - height, preferred.y)), width, height };
    };
    const preferred = { x: anchor.right - 360, y: anchor.bottom + gap };
    let result = fit(bounds, preferred);
    if (result.y < anchor.bottom && anchor.top - gap - result.height >= bounds.y)
      result.y = anchor.top - gap - result.height;
    if (!obstacle || obstacle.width <= 0 || obstacle.height <= 0 || !overlaps(result, obstacle)) return result;
    // A separate native game surface can cover HTML. Use a complete free area.
    const right = bounds.x + bounds.width, bottom = bounds.y + bounds.height;
    const areas = [
      { x: Math.max(bounds.x, obstacle.x + obstacle.width + gap), y: bounds.y,
        width: right - Math.max(bounds.x, obstacle.x + obstacle.width + gap), height: bounds.height },
      { x: bounds.x, y: bounds.y, width: Math.min(right, obstacle.x - gap) - bounds.x, height: bounds.height },
      { x: bounds.x, y: bounds.y, width: bounds.width, height: Math.min(bottom, obstacle.y - gap) - bounds.y },
      { x: bounds.x, y: Math.max(bounds.y, obstacle.y + obstacle.height + gap), width: bounds.width,
        height: bottom - Math.max(bounds.y, obstacle.y + obstacle.height + gap) },
    ].filter(area => area.width >= 120 && area.height >= 96);
    if (areas.length) {
      areas.sort((a, b) => Math.min(360, b.width) * Math.min(b.height, Math.min(360, b.width) * 9 / 16 + 72) -
        Math.min(360, a.width) * Math.min(a.height, Math.min(360, a.width) * 9 / 16 + 72));
      result = fit(areas[0], preferred);
    }
    return result;
  }

  function controller(options) {
    const setTimer = options.setTimer || setTimeout, clearTimer = options.clearTimer || clearTimeout;
    let generation = 0, timer = null, requestTimeout = null, request = null, current = null, last = false;
    function stop() {
      generation++; current = null; last = false;
      if (timer !== null) clearTimer(timer);
      if (requestTimeout !== null) clearTimer(requestTimeout);
      timer = requestTimeout = null; request?.abort(); request = null;
    }
    async function poll(revision, key) {
      if (revision !== generation || current !== key) return;
      const abort = new AbortController(); request = abort;
      const timeout = setTimer(() => abort.abort(), options.timeout || 5000);
      requestTimeout = timeout;
      try {
        const frame = await options.fetchFrame(key, abort.signal);
        if (revision !== generation || current !== key || abort.signal.aborted) return;
        last = true; options.showFrame(frame, key);
        options.showStatus("Gameplay screenshot · updated " + new Date().toLocaleTimeString());
      } catch (_) {
        if (revision !== generation || current !== key) return;
        options.showStatus(last ? "Frame unavailable; last screenshot shown" : "Gameplay frame is not available yet");
      } finally {
        clearTimer(timeout);
        if (requestTimeout === timeout) requestTimeout = null;
        if (request === abort) request = null;
        if (revision === generation && current === key)
          timer = setTimer(() => poll(revision, key), options.interval || 3000);
      }
    }
    return {
      open(key) { stop(); current = key; const revision = generation;
        options.showStatus("Loading gameplay screenshot…"); poll(revision, key); },
      close: stop,
    };
  }

  function mount(options = {}) {
    const doc = options.document || document, win = options.window || window;
    if (doc.getElementById("session-hover-preview")) return;
    const style = doc.createElement("style");
    style.textContent = `#session-hover-preview{position:fixed;z-index:110;box-sizing:border-box;display:none;grid-template-rows:44px minmax(0,1fr) 28px;
      overflow:hidden;background:var(--bg,#17181f);color:var(--fg,#ececf4);border:1px solid var(--line,#414552);
      border-radius:10px;box-shadow:0 12px 40px #000a;font:12px system-ui}
      #session-hover-preview .preview-heading{display:flex;gap:8px;align-items:center;padding:9px 10px}
      #session-hover-preview .preview-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:650}
      #session-hover-preview button{background:transparent;color:inherit;border:0;font:18px system-ui;cursor:pointer}
      #session-hover-preview .preview-frame{background:#000;display:grid;place-items:center;min-width:0;min-height:0;overflow:hidden}
      #session-hover-preview img{display:none;width:100%;height:100%;min-width:0;min-height:0;object-fit:contain}
      #session-hover-preview .preview-status{box-sizing:border-box;padding:6px 10px;font-size:11px;line-height:16px;color:var(--mut,#aab0c0);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}`;
    doc.head.append(style);
    const panel = doc.createElement("aside"); panel.id = "session-hover-preview";
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Game session preview");
    panel.innerHTML = '<div class="preview-heading"><span class="preview-title"></span><button type="button" aria-label="Close session preview">×</button></div>' +
      '<div class="preview-frame"><img alt="Current gameplay screenshot"></div><div class="preview-status" role="status"></div>';
    doc.body.append(panel);
    const title = panel.querySelector(".preview-title"), image = panel.querySelector("img"), status = panel.querySelector(".preview-status");
    let active = null, url = null, openTimer = null, closeTimer = null, description = null;
    const rect = () => {
      const game = doc.getElementById("nativeslot"), r = game?.getBoundingClientRect();
      return r && r.width > 0 && r.height > 0 ? { x: r.x, y: r.y, width: r.width, height: r.height } : null;
    };
    function position() {
      if (!active?.isConnected) { close(); return; }
      const p = placement(active.getBoundingClientRect(), { width: win.innerWidth, height: win.innerHeight }, rect());
      Object.assign(panel.style, { left: p.x + "px", top: p.y + "px", width: p.width + "px", height: p.height + "px" });
    }
    function clearImage() { if (url) win.URL.revokeObjectURL(url); url = null; image.removeAttribute("src"); image.style.display = "none"; }
    const monitor = controller({
      fetchFrame: async (sid, signal) => {
        const path = `/api/sessions/${encodeURIComponent(sid)}/frame.jpg`;
        const auth = typeof tq === "function" ? tq() : "";
        const response = await win.fetch(options.url ? options.url(path) : path + "?" + auth + "&t=" + Date.now(), { signal, cache: "no-store" });
        if (!response.ok) throw new Error("Frame unavailable");
        const blob = await response.blob();
        if (!blob.type.startsWith("image/") || !blob.size) throw new Error("Invalid frame");
        return blob;
      },
      showFrame: blob => { clearImage(); url = win.URL.createObjectURL(blob); image.src = url; image.style.display = "block"; },
      showStatus: text => { status.textContent = text; status.title = text; },
    });
    function clearPending() { win.clearTimeout(openTimer); win.clearTimeout(closeTimer); openTimer = closeTimer = null; }
    function close() {
      clearPending(); monitor.close(); panel.style.display = "none"; clearImage();
      if (active) {
        if (description === null) active.removeAttribute("aria-describedby");
        else active.setAttribute("aria-describedby", description);
      }
      active = null;
    }
    function describe(chip) {
      active = chip; description = chip.getAttribute("aria-describedby");
      chip.setAttribute("aria-describedby", [description, panel.id].filter(Boolean).join(" "));
      title.textContent = chip.getAttribute("title")?.split(/\s[·•]\s/)[0] || chip.querySelector("span")?.textContent || "Game session";
      title.title = chip.getAttribute("title") || title.textContent;
    }
    function open(chip) {
      clearPending(); if (active === chip) return;
      close(); describe(chip);
      panel.style.display = "grid"; position(); monitor.open(chip.dataset.sid);
    }
    const chipFor = target => target?.closest?.("#tray .tchip[data-sid]");
    doc.addEventListener("mouseover", event => {
      const chip = chipFor(event.target); if (!chip || chip.contains(event.relatedTarget)) return;
      clearPending(); openTimer = win.setTimeout(() => open(chip), 180);
    });
    doc.addEventListener("mouseout", event => {
      if (!chipFor(event.target)) return;
      if (active?.contains(event.relatedTarget) || panel.contains(event.relatedTarget)) return;
      win.clearTimeout(openTimer); closeTimer = win.setTimeout(close, 140);
    });
    doc.addEventListener("focusin", event => { const chip = chipFor(event.target); if (chip) open(chip); });
    doc.addEventListener("focusout", event => {
      if (active?.contains(event.relatedTarget) || panel.contains(event.relatedTarget)) return;
      if (chipFor(event.target) || panel.contains(event.target)) close();
    });
    panel.addEventListener("mouseenter", () => win.clearTimeout(closeTimer));
    panel.addEventListener("mouseleave", event => { if (!active?.contains(event.relatedTarget)) closeTimer = win.setTimeout(close, 140); });
    panel.querySelector("button").onclick = event => { event.stopPropagation(); const chip = active; close(); chip?.focus({ preventScroll: true }); close(); };
    doc.addEventListener("keydown", event => { if (event.key === "Escape" && active) { event.stopPropagation(); close(); } }, true);
    doc.addEventListener("click", event => { if (!panel.contains(event.target)) close(); });
    doc.addEventListener("contextmenu", close);
    win.addEventListener("blur", close);
    win.addEventListener("resize", position);
    doc.addEventListener("visibilitychange", () => { if (doc.hidden) close(); });
    new win.MutationObserver(() => {
      if (!active || active.isConnected) return;
      const replacement = [...doc.querySelectorAll("#tray .tchip[data-sid]")].find(chip => chip.dataset.sid === active.dataset.sid);
      if (!replacement) { close(); return; }
      if (description === null) active.removeAttribute("aria-describedby");
      else active.setAttribute("aria-describedby", description);
      // Routine tray redraw must keep the same frame request and polling clock.
      describe(replacement); position();
    }).observe(doc.getElementById("tray") || doc.body, { childList: true, subtree: true });
    image.onerror = () => { clearImage(); status.textContent = "Gameplay screenshot could not be displayed"; };
    return { close, panel };
  }
  return { placement, controller, mount };
});
