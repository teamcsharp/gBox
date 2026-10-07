// gBox visualizer: public API. See README.md.
import { VisualizerManager, QUALITY } from "./core/manager.js";
import { DemoProvider, MicrophoneProvider, ExternalProvider } from "./core/providers.js";
import { PALETTE_NAMES, resolvePalette } from "./core/palettes.js";
import { Hud } from "./core/hud.js";

export const MODES = [
  { id: "smooth-wave", n: 1, name: "Smooth Wave" },
  { id: "particle-flow", n: 2, name: "Particle Flow" },
  { id: "line-spectrum", n: 3, name: "Line Spectrum" },
  { id: "geometric-space", n: 4, name: "Geometric Space" },
  { id: "speed-lines", n: 5, name: "Speed Lines" },
  { id: "anime-ink", n: 6, name: "Anime Ink Wave" },
  { id: "audio-bars", n: 7, name: "Audio Bars" },
  { id: "liquid-glass", n: 8, name: "Liquid Glass" },
  { id: "retro-grid", n: 9, name: "Retro Grid" },
  { id: "shape-burst", n: 10, name: "Shape Burst" },
];
export const PALETTES = PALETTE_NAMES.slice();

const LAST_KEY = "gbox_viz_last";
const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const isMode = (id) => MODES.some((m) => m.id === id);

// random mode, different from the last one used (remembered across page loads)
export function pickRandomMode(exclude) {
  const last = exclude || lsGet(LAST_KEY);
  const pool = MODES.filter((m) => m.id !== last);
  return pool[(Math.random() * pool.length) | 0].id;
}

// the stored picker preference ("random" or a mode id) without attaching anything
export function readVizPref(storageKey = "gbox_viz_mode") {
  const v = lsGet(storageKey);
  return v && (v === "random" || isMode(v)) ? v : "random";
}

let presetsPromise = null;
function loadPresets() {
  if (!presetsPromise) presetsPromise = fetch(new URL("./presets.json", import.meta.url)).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return presetsPromise;
}

export async function createViz(canvas, opts = {}) {
  const o = { mode: "random", palette: "PlayStation Blue", quality: "auto", provider: "demo", wsUrl: null, hud: false, keys: false, cycleSecs: 0, ...opts };
  const presets = await loadPresets();
  const mgr = new VisualizerManager(canvas, { presets, quality: o.quality, palette: o.palette });
  let hud = null, requested = o.mode, cycleT = performance.now(), disposed = false, keyHandler = null;

  const ctl = {
    manager: mgr,
    get state() { return mgr.signal.state; },
    get requestedMode() { return requested; },
    async setMode(id = "random", { transition = "crossfade", instant = false } = {}) {
      requested = id;
      let target = id === "random" || !isMode(id) ? pickRandomMode(mgr.active && mgr.active.id) : id;
      lsSet(LAST_KEY, target);
      cycleT = performance.now();
      try { return await mgr.setMode(target, { transition, instant }); }
      catch (e) {
        console.error(`[viz] mode "${target}" failed:`, e);
        if (!mgr.active && target !== "smooth-wave") return mgr.setMode("smooth-wave", { instant: true });
        return mgr.active && mgr.active.id;
      }
    },
    getMode() { return mgr.active ? mgr.active.id : null; },
    list() { return MODES.map((m) => ({ ...m })); },
    palettes() { return PALETTES.slice(); },
    getPalette() { return mgr.paletteName; },
    getQuality() { return mgr.autoQ ? "auto" : mgr.qualityName; },
    start() { if (!disposed) mgr.start(); },
    stop() { mgr.stop(); },
    resize() { mgr.ctx.w = -1; mgr.resize(); },
    async setProvider(kind = "demo", { wsUrl } = {}) {
      let p;
      if (kind === "mic") p = new MicrophoneProvider();
      else if (kind === "external") p = new ExternalProvider(wsUrl || o.wsUrl, mgr.signal);
      else p = new DemoProvider();
      try { await mgr.setProvider(p); }
      catch (e) { console.warn(`[viz] provider "${kind}" failed, falling back to demo:`, e); if (kind !== "demo") await mgr.setProvider(new DemoProvider()); throw e; }
      return kind;
    },
    setPalette(name) { mgr.setPalette(name); return mgr.paletteName; },
    setQuality(q) { mgr.setQuality(q === "auto" || QUALITY[q] ? q : "auto"); },
    push(partial) { mgr.signal.push(partial); },
    toggleHud(force) {
      const on = force === undefined ? !hud : !!force;
      if (on && !hud) hud = new Hud(ctl, mgr);
      else if (!on && hud) { hud.dispose(); hud = null; }
      return !!hud;
    },
    dispose() {
      disposed = true;
      if (keyHandler) window.removeEventListener("keydown", keyHandler);
      if (hud) hud.dispose();
      mgr.dispose();
    },
  };

  mgr.onFrame = (dt, S) => {
    if (hud) hud.update(dt, S);
    if (o.cycleSecs > 0 && !mgr.trans && performance.now() - cycleT > o.cycleSecs * 1000) { cycleT = performance.now(); ctl.setMode("random", { transition: Math.random() < 0.5 ? "crossfade" : "dissolve" }).then(() => { requested = o.mode; }); }
  };

  if (o.keys) {
    keyHandler = (e) => {
      const t = e.target;
      if (e.ctrlKey || e.altKey || e.metaKey || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
      const k = e.key;
      if (k >= "0" && k <= "9") { ctl.setMode(MODES[(+k + 9) % 10].id); }
      else if (k === "h" || k === "H" || k === "`") ctl.toggleHud();
      else if (k === "m" || k === "M") ctl.setProvider("mic").catch(() => {});
      else if (k === "d" || k === "D") ctl.setProvider("demo");
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", keyHandler);
  }

  try { await ctl.setProvider(o.provider, { wsUrl: o.wsUrl }); } catch (e) {}
  await ctl.setMode(o.mode, { instant: true });
  requested = o.mode;
  if (o.hud) ctl.toggleHud(true);
  mgr.start();
  return ctl;
}

// ------------------------------------------------------------------ right-click picker
let styleDone = false;
function injectStyle() {
  if (styleDone) return; styleDone = true;
  const s = document.createElement("style");
  s.textContent = `
.gbviz-menu{position:fixed;z-index:2147483600;min-width:220px;max-height:calc(100vh - 16px);overflow:auto;padding:6px;border-radius:12px;
  background:rgba(6,14,38,.92);border:1px solid rgba(80,170,255,.35);box-shadow:0 12px 40px rgba(0,0,0,.55),0 0 0 1px rgba(0,0,0,.3) inset;
  backdrop-filter:blur(10px);color:#d6e8ff;font:13px/1.2 system-ui,-apple-system,"Segoe UI",sans-serif;user-select:none}
.gbviz-menu .h{padding:6px 10px 4px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#6f97c6}
.gbviz-menu .i{display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:7px;cursor:pointer;white-space:nowrap}
.gbviz-menu .i:hover,.gbviz-menu .i:focus{background:linear-gradient(90deg,rgba(31,86,232,.55),rgba(47,210,255,.25));color:#fff;outline:none}
.gbviz-menu .n{width:18px;text-align:right;color:#6f97c6;font-variant-numeric:tabular-nums}
.gbviz-menu .c{width:14px;color:#2fd2ff}
.gbviz-menu .sep{height:1px;margin:5px 6px;background:rgba(120,170,255,.2)}`;
  document.head.appendChild(s);
}

export function attachPicker(el, controller, { storageKey = "gbox_viz_mode" } = {}) {
  injectStyle();
  const palKey = storageKey + "_palette";
  let menu = null;
  const getCtl = () => controller;
  const storedPal = lsGet(palKey);
  if (storedPal && controller && controller.setPalette) controller.setPalette(storedPal);

  const close = () => {
    if (!menu) return;
    menu.remove(); menu = null;
    document.removeEventListener("pointerdown", onDocDown, true);
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("blur", close);
  };
  const onDocDown = (e) => { if (menu && !menu.contains(e.target)) close(); };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };

  const open = (x, y) => {
    close();
    const ctl = getCtl(); if (!ctl) return;
    const pref = readVizPref(storageKey), curPal = ctl.getPalette ? ctl.getPalette() : resolvePalette(lsGet(palKey));
    menu = document.createElement("div");
    menu.className = "gbviz-menu"; menu.setAttribute("role", "menu");
    const head = (t) => { const d = document.createElement("div"); d.className = "h"; d.textContent = t; menu.appendChild(d); };
    const item = (n, label, checked, fn) => {
      const d = document.createElement("div"); d.className = "i"; d.tabIndex = 0; d.setAttribute("role", "menuitemradio"); d.setAttribute("aria-checked", checked);
      d.innerHTML = `<span class="c">${checked ? "&#10003;" : ""}</span><span class="n">${n}</span><span></span>`;
      d.lastChild.textContent = label;
      d.addEventListener("click", (e) => { e.stopPropagation(); fn(); close(); });
      d.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); close(); } });
      menu.appendChild(d);
    };
    head("Visualizer");
    item("", "Random (each title)", pref === "random", () => { lsSet(storageKey, "random"); ctl.setMode("random", { transition: "crossfade" }); });
    for (const m of MODES) item(m.n, m.name, pref === m.id, () => { lsSet(storageKey, m.id); ctl.setMode(m.id, { transition: "crossfade" }); });
    const sep = document.createElement("div"); sep.className = "sep"; menu.appendChild(sep);
    head("Palette");
    for (const p of PALETTES) item("", p, p === curPal, () => { lsSet(palKey, p); ctl.setPalette(p); });
    document.body.appendChild(menu);
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(x, window.innerWidth - r.width - 8)) + "px";
    menu.style.top = Math.max(8, Math.min(y, window.innerHeight - r.height - 8)) + "px";
    document.addEventListener("pointerdown", onDocDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("blur", close);
  };

  el.addEventListener("contextmenu", (e) => { e.preventDefault(); open(e.clientX, e.clientY); });
  return readVizPref(storageKey);
}
