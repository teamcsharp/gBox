// gBox desktop UI performance probe (#712, #1081).
//
// Runs the desktop shell (clients/desktop/index.html) and its embedded gBox view (clients/web) from a chosen checkout
// in an isolated Electron instance, and measures what the UI costs while idle and while switching sections:
//   - main-thread work per renderer (Chromium DevTools Performance metrics: task/script/layout/style time and counts),
//   - CPU seconds per Electron process (browser, GPU, renderers),
//   - every control-plane request the UI makes (count + bytes per endpoint),
//   - long tasks (>50 ms) and the frame rate the renderer actually produced,
//   - click-to-paint latency of the sidebar sections (with --interact).
//
// It is read-only against the gBox API: GETs are forwarded, every other method is refused locally, and live
// video/desktop streams are not opened. It never starts a worker, never touches game windows (embed calls are stubbed)
// and runs in its own profile, so it is safe beside the operator's running app.
//
//   "%LOCALAPPDATA%\gbox\app\gBox.exe" system\scripts\ui-perf --seconds 60 --out before.json
//   options: --clients <dir> (default: this checkout's clients/)  --api <url>  --token-file <path>
//            --section play|control|requests|settings|tools   --docked (a synthetic docked game, native-window path)
//            --interact (section switch latency)   --visible (show the window on screen; default: off-screen, no focus)
//            --update-pending (the logo's "update ready" state, as after a deploy while the app runs)
//            --simulate-etag (tag /api/requests by a body hash when the control plane does not send ETags yet)
"use strict";
const { app, BrowserWindow, ipcMain, protocol, net, session, screen } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

const argv = process.argv.slice(1);
const opt = (name, dflt) => { const i = argv.indexOf("--" + name); return i < 0 ? dflt : (argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : true); };
const CLIENTS = path.resolve(opt("clients", path.join(__dirname, "..", "..", "clients")));
const API = new URL(opt("api", process.env.GBOX_API_URL || "http://10.89.1.246:8765"));
const TOKEN_FILE = opt("token-file", "\\\\10.89.1.246\\ehm_eckx\\gBox\\system\\gbox-data\\api_token");
const SECONDS = +opt("seconds", 60), WARMUP = +opt("warmup", 15);
const SECTION = opt("section", "play"), DOCKED = !!opt("docked", false), INTERACT = !!opt("interact", false), VISIBLE = !!opt("visible", false);
const OUT = opt("out", "");
const UPDATE_PENDING = !!opt("update-pending", false);   // the logo's "update ready" state (new code on disk since the app started)
const SIMULATE_ETAG = !!opt("simulate-etag", false);
const WORKER = "PERF-PROBE";
const TOKEN = process.env.GBOX_TOKEN || fs.readFileSync(TOKEN_FILE, "utf8").trim();

app.setPath("userData", fs.mkdtempSync(path.join(os.tmpdir(), "gbox-ui-perf-")));
for (const sw of ["ignore-gpu-blocklist", "enable-gpu-rasterization", "enable-zero-copy", "force_high_performance_gpu"]) app.commandLine.appendSwitch(sw);
app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", API.origin);
// an off-screen window must keep rendering like the real, visible one
app.commandLine.appendSwitch("disable-features", "CalculateNativeWinOcclusion");

// ---------------- request accounting ----------------
const REQ = new Map();          // "via METHOD /normalized/path" -> { n, bytes, ms }
let measuring = false;
const norm = p => p.replace(/[0-9a-f]{16,}(-[0-9a-f]{8,})?/gi, ":id").replace(/\d{3,}/g, ":n");
function count(via, method, url, bytes, ms) {
  if (!measuring) return;
  const u = new URL(url, API);
  const key = `${via} ${method} ${norm(u.pathname)}${u.search.includes("include_ended=false") ? "?running" : ""}`;
  const e = REQ.get(key) || { n: 0, bytes: 0, ms: 0 };
  e.n++; e.bytes += bytes; e.ms += ms; REQ.set(key, e);
}
const STREAM = /\/(mjpeg|stream|webrtc|desktop|frame|audio)(\/|$|\?)/;
const FAKE = { session_id: "perfprobe0000001-perfprobe", state: "running", adapter: "dolphin", title: "Probe Game", game_id: "perf-probe",
  started: Date.now() / 1000, capabilities: [], detail: { local_window: true, worker_name: WORKER, pid: 4, status: "running" } };
async function apiFetch(via, method, url, init = {}) {
  const t = Date.now();
  if (method !== "GET" && method !== "HEAD") {
    count(via, method + "(refused)", url, 0, 0);
    return new Response(JSON.stringify({ detail: "ui-perf probe is read-only" }), { status: 403, headers: { "content-type": "application/json" } });
  }
  if (STREAM.test(new URL(url).pathname)) { count(via, "GET(stream refused)", url, 0, 0); return new Response("", { status: 404 }); }
  const r = await net.fetch(url, { ...init, method, bypassCustomProtocolHandlers: true });
  let buf = Buffer.from(await r.arrayBuffer());
  const p = new URL(url).pathname;
  if (DOCKED && p === "/api/sessions" && r.ok) {
    try { const list = JSON.parse(buf); list.unshift({ ...FAKE }); buf = Buffer.from(JSON.stringify(list)); } catch {}
  }
  count(via, method, url, buf.length, Date.now() - t);
  const headers = new Headers(r.headers); headers.delete("content-length"); headers.delete("content-encoding");
  return new Response(buf, { status: r.status, headers });
}

// ---------------- the main-process API surface the shell expects (preload.js) ----------------
const SETTINGS = { apiUrl: API.origin, workerName: WORKER, sshHost: "", repoLocal: path.resolve(CLIENTS, ".."), repoShare: "",
  repoRemote: "", token: "", autoStartWorker: false, volume: 0 };
const IPC = {
  "settings:get": () => SETTINGS, "settings:save": () => SETTINGS, token: () => TOKEN,
  api: async (_e, p, body) => {
    try {
      const r = await apiFetch("shell-ipc", body ? "POST" : "GET", API.origin + p, { headers: { authorization: `Bearer ${TOKEN}` } });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      return { ok: true, data: await r.json() };
    } catch (e) { return { ok: false, error: e.message }; }
  },
  // main.js's tagged read: the data only when its ETag changed. --simulate-etag stands in for a control plane that does
  // not send ETags yet (a hash of the body), so the client side can be measured before the server is deployed.
  "api:tagged": async (_e, p, have) => {
    try {
      const r = await apiFetch("shell-ipc", "GET", API.origin + p, { headers: { authorization: `Bearer ${TOKEN}` } });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const text = await r.text();
      const etag = r.headers.get("etag") || (SIMULATE_ETAG ? require("crypto").createHash("sha1").update(text).digest("hex") : null);
      return etag && etag === have ? { ok: true, etag, unchanged: true } : { ok: true, etag, data: JSON.parse(text) };
    } catch (e) { return { ok: false, error: e.message }; }
  },
  "audio:volume": () => ({ volume: 0, available: false }),
  "spark:status": () => ({ ssh: true, service: "active", api: true, mount: "mounted", uptime: "probe", free: "-", gpu: "-" }),
  "win:worker": () => ({ running: true }), "pad:devices": () => [], "task:snapshot": () => [],
  "update:pending": () => ({ pending: UPDATE_PENDING, changed: UPDATE_PENDING ? "probe" : "", file: UPDATE_PENDING ? "probe" : "" }),
  "embed:sync": (_e, st) => {
    if (measuring) STATS.embedSync++;
    if (st && !st.surface) SYNCS.push({ t: Date.now(), holes: (st.holes || []).length, visible: st.visible });
    return st && st.surface ? { ok: false, error: "probe: no capture" } : { ok: true };
  },
  "embed:release": () => ({ ok: true }), "embed:focus": () => ({ ok: true }), "embed:kill": () => ({ ok: true }), "app:focus": () => ({ ok: true }),
  "viz:overlay": () => ({ on: false }), overlay: () => ({ ok: false }), "console:tail": () => "", "rec:screens": () => [],
};
const STATS = { embedSync: 0 }, SYNCS = [];
const CHANNELS = ["settings:save", "spark:action", "win:setup", "task:cancel", "open:external", "app:relaunch", "capture", "capture:os",
  "report:clipboard-files", "stt", "tts", "mini:open", "mini:aspect", "mini:restore", "rec:start", "rec:crop", "rec:abort", "rec:chunk",
  "rec:stop", "rec:fit", "rec:open", "export:pdf", "clip:image", "win:fullscreen", "browser:send", "decant:plan", "decant:save",
  "decant:cancel", "decant:show", "settings:reset-token"];
for (const ch of CHANNELS) if (!IPC[ch]) IPC[ch] = () => null;
for (const [ch, fn] of Object.entries(IPC)) ipcMain.handle(ch, fn);

// ---------------- serve the checkout's web client in place of the Spark's copy ----------------
function staticFile(p) {
  const web = path.join(CLIENTS, "web");
  if (p === "/" || p === "/index.html") return path.join(web, "index.html");
  if (p.startsWith("/viz/")) { const f = path.resolve(web, "viz", "." + p.slice(4)); return f.startsWith(path.join(web, "viz")) ? f : null; }
  return null;
}
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

async function metrics(wc) {
  const r = await wc.debugger.sendCommand("Performance.getMetrics");
  return Object.fromEntries(r.metrics.map(m => [m.name, m.value]));
}
// No requestAnimationFrame counter: a rAF loop would itself keep the compositor producing frames. Endless animations are
// listed instead (each one keeps the renderer and GPU process drawing at the display's refresh rate).
const INSTRUMENT = `(() => { if (window.__probe) return; const p = window.__probe = { long: 0, longMs: 0, maxLong: 0 };
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) { p.long++; p.longMs += e.duration; p.maxLong = Math.max(p.maxLong, e.duration); } }).observe({ type: "longtask" }); } catch {} })()`;
const READ = `(() => { const p = window.__probe || {}; return { long: p.long, longMs: Math.round(p.longMs), maxLong: Math.round(p.maxLong),
  nodes: document.getElementsByTagName("*").length,
  endless: document.getAnimations().filter(a => a.playState === "running" && a.effect?.getTiming().iterations === Infinity)
    .map(a => (a.animationName || "anim") + "@" + (a.effect.target?.id || a.effect.target?.className || a.effect.target?.tagName || "?")) }; })()`;

function cpuNow() {
  const out = {};
  for (const m of app.getAppMetrics()) out[m.pid] = { type: m.type + (m.serviceName ? ":" + m.serviceName : ""), cpu: m.cpu.cumulativeCPUUsage ?? 0 };
  return out;
}

app.whenReady().then(async () => {
  protocol.handle("http", async req => {
    const u = new URL(req.url);
    if (u.origin === API.origin) {
      const f = staticFile(u.pathname);
      if (f && fs.existsSync(f)) return new Response(fs.readFileSync(f), { headers: { "content-type": MIME[path.extname(f)] || "application/octet-stream", "cache-control": "no-cache" } });
      // the embedded view is served from the API origin; the shell is a file:// page (its <img> loads carry no such referrer)
      if (u.pathname.startsWith("/api/")) return apiFetch(String(req.referrer || "").startsWith(API.origin) ? "guest-http" : "shell-http", req.method, req.url, { headers: req.headers });
    }
    return net.fetch(req, { bypassCustomProtocolHandlers: true });
  });
  const guests = [];
  app.on("web-contents-created", (_e, wc) => { if (wc.getType() === "webview") guests.push(wc); });
  const all = screen.getAllDisplays().map(d => d.bounds);
  const right = Math.max(...all.map(b => b.x + b.width));
  const win = new BrowserWindow({ width: 1500, height: 950, x: VISIBLE ? undefined : right + 200, y: VISIBLE ? undefined : 0, show: false,
    focusable: VISIBLE, backgroundColor: "#16161a", titleBarStyle: "hidden", titleBarOverlay: { color: "#111114", symbolColor: "#e8e8ee", height: 36 },
    webPreferences: { preload: path.join(CLIENTS, "desktop", "preload.js"), contextIsolation: true, nodeIntegration: false, webviewTag: true, backgroundThrottling: false } });
  await win.loadFile(path.join(CLIENTS, "desktop", "index.html"));
  VISIBLE ? win.show() : win.showInactive();
  const wcs = { shell: win.webContents };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const t0Load = Date.now();
  while (!guests.length && Date.now() - t0Load < 30000) await sleep(250);
  if (guests[0]) wcs.guest = guests[0];
  for (const wc of Object.values(wcs)) { wc.debugger.attach("1.3"); await wc.debugger.sendCommand("Performance.enable"); }
  if (SECTION !== "play") await win.webContents.executeJavaScript(`document.querySelector('aside button[data-s="${SECTION}"]')?.click()`);
  await sleep(WARMUP * 1000);
  for (const wc of Object.values(wcs)) await wc.executeJavaScript(INSTRUMENT).catch(() => {});
  const m0 = {}; for (const [k, wc] of Object.entries(wcs)) m0[k] = await metrics(wc);
  const c0 = cpuNow(); const t0 = Date.now(); measuring = true;
  await sleep(SECONDS * 1000);
  measuring = false; const dt = (Date.now() - t0) / 1000; const c1 = cpuNow();
  const result = { clients: CLIENTS, section: SECTION, docked: DOCKED, seconds: +dt.toFixed(1), renderers: {}, cpu: {}, requests: {}, embedSyncPerMin: +(STATS.embedSync * 60 / dt).toFixed(1) };
  for (const [k, wc] of Object.entries(wcs)) {
    const a = m0[k], b = await metrics(wc), page = await wc.executeJavaScript(READ).catch(() => ({}));
    const d = n => (b[n] ?? 0) - (a[n] ?? 0);
    result.renderers[k] = { busyPct: +(100 * d("TaskDuration") / dt).toFixed(1), scriptPct: +(100 * d("ScriptDuration") / dt).toFixed(1),
      layoutsPerMin: +(d("LayoutCount") * 60 / dt).toFixed(0), layoutMsPerMin: +(1000 * d("LayoutDuration") * 60 / dt).toFixed(0),
      styleRecalcsPerMin: +(d("RecalcStyleCount") * 60 / dt).toFixed(0), styleMsPerMin: +(1000 * d("RecalcStyleDuration") * 60 / dt).toFixed(0),
      endlessAnimations: page.endless, longTasksPerMin: +((page.long || 0) * 60 / dt).toFixed(1), longTaskMsPerMin: +((page.longMs || 0) * 60 / dt).toFixed(0),
      maxLongTaskMs: page.maxLong || 0, domNodes: page.nodes, jsHeapMB: +((b.JSHeapUsedSize || 0) / 2 ** 20).toFixed(1), listeners: b.JSEventListeners };
  }
  const byType = {};
  for (const [pid, e] of Object.entries(c1)) { const before = c0[pid]?.cpu ?? 0; byType[e.type] = (byType[e.type] || 0) + (e.cpu - before); }
  for (const [t, s] of Object.entries(byType)) result.cpu[t] = +(100 * s / dt).toFixed(1);
  result.cpu.total = +Object.values(result.cpu).reduce((x, y) => x + y, 0).toFixed(1);
  let n = 0, bytes = 0;
  for (const [k, e] of [...REQ.entries()].sort((x, y) => y[1].bytes - x[1].bytes)) {
    result.requests[k] = { perMin: +(e.n * 60 / dt).toFixed(1), kBPerMin: +(e.bytes * 60 / dt / 1024).toFixed(0), avgMs: Math.round(e.ms / e.n) };
    n += e.n; bytes += e.bytes;
  }
  result.requestTotals = { perMin: +(n * 60 / dt).toFixed(1), MBPerMin: +(bytes * 60 / dt / 2 ** 20).toFixed(2) };
  if (INTERACT) {
    const lat = {};
    for (const s of ["control", "requests", "settings", "tools", "play", "requests", "control", "play"]) {
      const ms = await win.webContents.executeJavaScript(`(async () => { const t = performance.now(); document.querySelector('aside button[data-s="${s}"]')?.click();
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); return performance.now() - t; })()`);
      (lat[s] ||= []).push(Math.round(ms)); await sleep(1500);
    }
    result.sectionSwitchMs = lat;
  }
  if (DOCKED) {
    // #1081: how long a pop-up over the docked native game stays hidden behind it (open) or leaves a hole (close):
    // the time from the DOM change to the embed sync that cuts / restores it. Shell pop-ups and embedded-view menus.
    const waitSync = async (since, test, ms = 5000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) { const s = SYNCS.find(x => x.t >= since && test(x)); if (s) return s.t - since; await sleep(5); }
      return null;
    };
    const holesNow = () => (SYNCS.at(-1) || { holes: 0 }).holes;
    const where = await win.webContents.executeJavaScript(`(() => { const r = EMB.rect, w = document.querySelector("#wv")?.getBoundingClientRect();
      return r ? { x: r.x + r.w / 2 - 80, y: r.y + r.h / 2 - 50, wx: w ? w.left : 0, wy: w ? w.top : 0 } : null; })()`);
    const lat = { shellOpen: [], shellClose: [], guestOpen: [], guestClose: [] };
    for (let i = 0; where && i < 12; i++) {
      const guest = i % 2 === 1 && wcs.guest;
      const target = guest ? wcs.guest : win.webContents;
      const x = guest ? where.x - where.wx : where.x, y = guest ? where.y - where.wy : where.y;
      await sleep(400 + Math.random() * 300);
      const h0 = holesNow(), t0p = Date.now();
      await target.executeJavaScript(`(() => { const d = document.createElement("div"); d.id = "probe-pop"; ${guest ? 'd.setAttribute("role", "menu");' : ""}
        d.style.cssText = "position:fixed;left:${x}px;top:${y}px;width:160px;height:100px;z-index:99;background:#335"; document.body.append(d); })()`);
      const open = await waitSync(t0p, s => s.holes > h0);
      await sleep(300 + Math.random() * 200);
      const t1p = Date.now();
      await target.executeJavaScript(`document.getElementById("probe-pop")?.remove()`);
      const close = await waitSync(t1p, s => s.holes <= h0);
      lat[guest ? "guestOpen" : "shellOpen"].push(open); lat[guest ? "guestClose" : "shellClose"].push(close);
    }
    const stat = a => { const v = a.filter(x => x != null).sort((p, q) => p - q);
      return { median: v[Math.floor(v.length / 2)] ?? null, max: v.at(-1) ?? null, missed: a.length - v.length }; };
    result.popupHoleLatencyMs = Object.fromEntries(Object.entries(lat).map(([k, a]) => [k, stat(a)]));
  }
  const text = JSON.stringify(result, null, 1);
  if (OUT) fs.writeFileSync(OUT, text);
  console.log(text);
  app.exit(0);
}).catch(e => { console.error(e); app.exit(1); });
