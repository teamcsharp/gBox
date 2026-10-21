// gBox desktop manager (Electron main process).
// Manages: the Spark control plane (over SSH: install/update, start/stop, logs), the local Windows worker,
// dependency setup on both nodes, and hosts the gBox web UI with the API token injected.
const { app, BrowserWindow, ipcMain, shell, desktopCapturer, session, screen, dialog, clipboard, nativeImage, globalShortcut, Menu, nativeTheme, Notification, powerSaveBlocker } = require("electron");
const { spawn, execFile, execFileSync } = require("child_process");
const embedGeometry = require("./embed-geometry");
const operationConsole = require('../web/viz/operation-console.js');
const coachTransport = require('./coach-transport');
const operationOutput = require('./operation-output-window.cjs')({BrowserWindow,getWin:()=>win});
ipcMain.handle('operation-console:frame',(_e,state)=>{operationOutput.update(state);});
// The shell and its guest are one dark app, including native controls and first paint.
nativeTheme.themeSource = "dark";

// gBox owns everything under a \gBox\runtime\ folder (RetroArch, "gBox Dolphin", Xenia, PCSX2...) plus its worker and window embedder:
// close all of them when the app closes, and sweep leftovers (a crash, a killed app) when it opens. Nothing else is touched.
// Standalone (a decanted install, gbox/decant.py): GBOX_STANDALONE_HOME = the install folder. The app then runs this PC's own
// control plane + worker (serve --worker), keeps its profile in the install folder, and only ever sweeps that install's processes.
const STANDALONE = process.env.GBOX_STANDALONE_HOME ? require("path").resolve(process.env.GBOX_STANDALONE_HOME) : null;
const psq = s => "'" + String(s).replace(/'/g, "''") + "'";
const CLEANUP_PS = STANDALONE ? `$me=$PID; $root=${psq(STANDALONE + "\\")}; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $me -and (
  ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + 'runtime\\', [StringComparison]::OrdinalIgnoreCase)) -or
  ($_.CommandLine -and $_.CommandLine.IndexOf($root.TrimEnd('\\'), [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
   ($_.CommandLine -match '-m gbox .*\\bworker\\b' -or $_.CommandLine -match 'winembed\\.py')) ) } |
  ForEach-Object { "$($_.ProcessId) $($_.Name)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`
  : `$me=$PID; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $me -and (
  ($_.ExecutablePath -and $_.ExecutablePath -like '*\\gBox\\runtime\\*') -or
  ($_.CommandLine -match '-m gbox .*\\bworker\\b' -or $_.CommandLine -match 'winembed\\.py') ) } |
  ForEach-Object { "$($_.ProcessId) $($_.Name)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
function cleanupSessions(sync) {
  const args = ["-NoProfile", "-NonInteractive", "-Command", CLEANUP_PS];
  if (sync) { try { return execFileSync("powershell.exe", args, { windowsHide: true, timeout: 15000 }).toString(); } catch (e) { return String(e); } }
  return new Promise(r => execFile("powershell.exe", args, { windowsHide: true, timeout: 15000 }, (_e, out) => r(String(out || ""))));
}
const fs = require("fs");
const os = require("os");
const path = require("path");
const clientHandoff = require('./client-handoff.cjs');
const clientViews = require('./client-view-store.cjs');
const recordingExport = require('./recording-export.cjs');

app.setPath("userData", STANDALONE ? path.join(STANDALONE, ".tools", "desktop-profile")       // standalone: own profile + single-instance lock
                                  : path.join(app.getPath("appData"), "gbox-desktop"));   // keep settings where they were (productName = gBox)
const GAME_FRAME_DIR = path.join(app.getPath("userData"), "game-frames");
process.env.GBOX_GAME_FRAME_DIR = GAME_FRAME_DIR;                  // worker/tracker also use a standalone profile's capture cache
const SETTINGS = path.join(app.getPath("userData"), "settings.json");
const CLIENT_HANDOFF_FILE = path.join(app.getPath('userData'), 'client-refresh-handoff.json');
const clientViewStore = clientViews.create(app.getPath('userData'));
let savedClientState = null, savedClientOrigin = null, savedClientKey = null, clientViewTimer = null;
let startupHandoff = null, handoffView = null, clientHandoffBusy = false, clientRefreshExit = false;
let clientActivation = { state: 'active', pid: process.pid, reason: 'Current desktop process is active.' };
const DEFAULTS = {
  sshHost: "spark",                                   // ~/.ssh/config alias (key auth, BatchMode); optional
  apiUrl: "http://10.89.1.246:8765",
  repoRemote: "~/gBox/system",                        // gBox system folder on the Spark
  repoLocal: path.resolve(__dirname, "..", ".."),     // this PC's checkout (share or GitHub clone): runs the worker
  repoShare: "\\\\10.89.1.246\\ehm_eckx\\gBox\\system",  // optional: the Spark's system folder over SMB (token lookup)
  token: "",                                          // optional: paste once if neither share nor SSH is reachable
  workerName: os.hostname(),
  autoStartWorker: true,
  volume: 30,
};
// Managed LAN desktops share exports; each desktop profile can override this folder.
const RECORDING_DEFAULTS = { ...recordingExport.DEFAULTS, exportDir: STANDALONE ? '' : '\\\\10.89.1.246\\spark_ext\\samples_grabbed\\user\\gBox' };
if (STANDALONE) Object.assign(DEFAULTS, { sshHost: "", apiUrl: process.env.GBOX_API_URL || "http://127.0.0.1:8765",
  repoLocal: path.join(STANDALONE, "system"), repoShare: path.join(STANDALONE, "system"), repoRemote: "" });
// Every API call reads the settings (#712): parse the file only when it changed, not 2-3 times per request.
let settingsCache = null, settingsStamp = null;
const settings = () => {
  let stamp = "none";
  try { const st = fs.statSync(SETTINGS); stamp = `${st.mtimeMs}:${st.size}`; } catch {}
  if (settingsCache && stamp === settingsStamp) return { ...settingsCache };
  settingsCache = readSettings(); settingsStamp = stamp;
  return { ...settingsCache };
};
const readSettings = () => {
  const s = { ...DEFAULTS, ...(fs.existsSync(SETTINGS) ? JSON.parse(fs.readFileSync(SETTINGS, "utf8")) : {}) };
  // layout migration: everything moved under <root>/system (root = gBox.exe + system/)
  if (/[\\/]gBox$/i.test(s.repoShare || "")) s.repoShare += "\\system";
  if ((s.repoRemote || "").replace(/\/$/, "") === "~/gBox") s.repoRemote = "~/gBox/system";
  if (!fs.existsSync(path.join(s.repoLocal || "", "gbox.toml"))) s.repoLocal = DEFAULTS.repoLocal;
  return s;
};
// The gBox UI is served over plain HTTP on the LAN; Chromium only exposes the microphone (dictation, Talk)
// to secure origins, so mark the configured Spark origin as trusted. Must run before the app is ready.
try { app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", new URL(settings().apiUrl).origin); } catch {}
// GPU: render the app on the fast GPU and never fall back to software because of Chromium's driver blocklist
for (const sw of ["ignore-gpu-blocklist", "enable-gpu-rasterization", "enable-zero-copy", "force_high_performance_gpu"]) app.commandLine.appendSwitch(sw);
app.on("gpu-info-update", () => { try { fs.writeFileSync(path.join(app.getPath("userData"), "gpu-status.json"),
  JSON.stringify({ features: app.getGPUFeatureStatus(), ts: new Date().toISOString() }, null, 1)); } catch {} });
const venvPython = () => STANDALONE ? path.join(STANDALONE, ".venv", "Scripts", "python.exe")
                                   : path.join(process.env.LOCALAPPDATA, "gbox", "venv", "Scripts", "python.exe");

let win, worker = null, workerControl = null, workerStopRequested = false, backgroundPower = null;
ipcMain.handle('background:power', () => backgroundPower?.snapshot() || {active:false,reason:'Display policy not started'});
const procs = new Map();                              // id -> child process (streamed tasks)
const taskLogs = new Map();                           // recent app commands and their streamed output
// console output of the whole app (main process, renderer + gBox webview, worker / task streams) for issue reports
let CONSOLE = "";
const logPush = (src, text) => { CONSOLE = (CONSOLE + `${new Date().toISOString().slice(11, 23)} [${src}] ${String(text).replace(/\n+$/, "")}\n`).slice(-400000); };
for (const lv of ["log", "warn", "error"]) { const orig = console[lv].bind(console); console[lv] = (...a) => { logPush("main:" + lv, a.map(String).join(" ")); orig(...a); }; }
app.on("web-contents-created", (_e, wc) => {
  if (wc.getType() === "webview") {
    wc.setBackgroundColor?.("#16161a");
    wc.setBackgroundThrottling(false);
  }
  wc.on("console-message", (ev, level, message, line, source) => {
  const m = ev?.message ?? message, lv = ev?.level ?? level, src = ev?.sourceId ?? source, ln = ev?.lineNumber ?? line;
  if (m === 'GBOX:{"ev":"layout"}') return;                 // the embedded view's menu-changed signal (#1081), not a log line
  logPush(`${wc.getType()}:${lv}`, `${m}${src ? `  (${String(src).split("/").pop()}:${ln})` : ""}`);
  });
  wc.on("render-process-gone", (_e, details) => {
    logPush(`${wc.getType()}:error`, `render-process-gone: reason=${details?.reason} exitCode=${details?.exitCode}`);
    if (wc.getType() === "window" && win && !win.isDestroyed() && wc === win.webContents) pickHoldReleaseAll("window crashed");
  });
});
ipcMain.handle("console:tail", (_e, n = 200000) => CONSOLE.slice(-n));
const send = (ch, ...a) => {
  if (ch === "task") {
    logPush(a[0], a[1]);
    const task = taskLogs.get(a[0]);
    if (task) task.output = (task.output + String(a[1])).slice(-50000);
  }
  return win && !win.isDestroyed() && win.webContents.send(ch, ...a);
};
function taskDone(id, code) {
  const task = taskLogs.get(id);
  if (!task) return;
  task.state = "ended"; task.exit_code = code; task.ended = Date.now() / 1000;
  setTimeout(() => { if (taskLogs.get(id) === task) taskLogs.delete(id); }, 300000).unref();
}

function stream(id, cmd, args, opts = {}) {
  if (clientHandoffBusy) throw Error('Desktop refresh is checking local activity. Try again when it finishes.');
  // Run a command, streaming stdout/stderr lines to the renderer as `task:<id>` events.
  return new Promise(resolve => {
    const p = spawn(cmd, args, { windowsHide: true, ...opts });
    procs.set(id, p);
    taskLogs.set(id, { id, pid: p.pid, started: Date.now() / 1000, state: "running", output: "" });
    const out = d => send("task", id, d.toString());
    p.stdout.on("data", out); p.stderr.on("data", out);
    p.on("error", e => { send("task", id, `\n[error] ${e.message}\n`); });
    p.on("close", code => {
      procs.delete(id);
      taskDone(id, code);
      send("task-end", id, code); resolve(code);
    });
  });
}

function ssh(cmd, timeout = 20000) {
  return new Promise(resolve => execFile("ssh", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", settings().sshHost, cmd],
    { timeout, windowsHide: true }, (err, stdout, stderr) => resolve({ ok: !err, code: err?.code ?? 0, out: stdout, err: stderr })));
}

let cachedToken = null;
async function token() {
  // Pairing order: pasted token -> Spark share file -> SSH. Cached for the session.
  const s = settings();
  if (s.token) return s.token;
  if (cachedToken) return cachedToken;
  try { cachedToken = fs.readFileSync(path.join(s.repoShare, "gbox-data", "api_token"), "utf8").trim(); return cachedToken; } catch {}
  const r = await ssh(`cat ${s.repoRemote}/gbox-data/api_token`, 8000);
  if (r.ok && r.out.trim()) cachedToken = r.out.trim();
  return cachedToken;
}

// GET answers the control plane tags (ETag): re-asking costs a 304, not a download and a parse (#712: /api/requests ~8 MB)
const ETAGS = new Map();                              // path -> { etag, data }
async function api(p, body, method) {
  return operationConsole.trace(event=>send('operation-console',event),p,body,async()=>{
    const data=await apiRaw(p,body,method);
    if(p.startsWith('/api/jobs/')&&data?.id&&data?.state)send('operation-console',{job:data});
    return data;
  });
}
async function apiRaw(p, body, method) {               // method: PATCH / PUT / DELETE when asked, else POST with a body
  const t = await token();
  method = /^(GET|POST|PUT|PATCH|DELETE)$/.test(String(method || "").toUpperCase()) ? String(method).toUpperCase() : (body ? "POST" : "GET");
  const known = method === "GET" && !body && ETAGS.get(p);
  const r = await fetch(settings().apiUrl + p, {
    method, body: body && method !== "GET" ? JSON.stringify(body) : undefined,
    headers: { authorization: `Bearer ${t}`, "content-type": "application/json", ...(known ? { "if-none-match": known.etag } : {}) },
    // long polls get 35 s; asset listings 20 s (the control plane may still be indexing a slow HDD); the rest 8 s
    signal: AbortSignal.timeout(coachTransport.timeoutMs(p, method) || (p === "/api/tasks" || p.startsWith("/api/tasks?") ? 35000
      : p.startsWith("/api/asset-groups") || p.startsWith("/api/assets?") ? 20000 : 8000)),
  });
  if (r.status === 304 && known) return known.data;
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  const data = await r.json(), etag = method === "GET" && r.headers.get("etag");
  if (etag) ETAGS.set(p, { etag, data }); else ETAGS.delete(p);
  return data;
}

// Windows keeps one mixer volume per playback session. This helper follows gBox's
// Electron and emulator processes so the slider also reaches games started later.
let audioVolumeHelper = null, audioVolumeFailures = 0, quitting = false;
const volumePercent = value => Math.max(0, Math.min(100, Number.isFinite(+value) ? Math.round(+value) : 30));
function startAudioVolumeHelper() {
  if (process.platform !== "win32" || audioVolumeHelper) return !!audioVolumeHelper;
  const py = venvPython(), s = settings();
  if (!fs.existsSync(py) || audioVolumeFailures >= 3) return false;
  const child = spawn(py, ["-u", "-m", "gbox.audio_volume", "--owner-pid", String(process.pid),
    "--config", path.join(s.repoLocal, "gbox.toml"), "--volume", String(volumePercent(s.volume))],
  { env: { ...process.env, PYTHONPATH: s.repoLocal }, windowsHide: true });
  audioVolumeHelper = child;
  child.stderr.on("data", data => logPush("audio", data.toString()));
  child.on("error", error => logPush("audio", error.message));
  child.on("close", code => {
    audioVolumeHelper = null;
    if (!quitting && ++audioVolumeFailures < 3) setTimeout(startAudioVolumeHelper, 5000).unref();
    else if (!quitting) logPush("audio", `volume helper exited ${code}`);
  });
  return true;
}
ipcMain.handle("audio:volume", (_e, value) => {
  if (value != null) {
    const volume = volumePercent(value);
    const s = settings();
    fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
    fs.writeFileSync(SETTINGS, JSON.stringify({ ...s, volume }, null, 1)); settingsStamp = null;
    audioVolumeFailures = 0;
    if (!audioVolumeHelper) startAudioVolumeHelper();
    try { audioVolumeHelper?.stdin.write(String(volume) + "\n"); }
    catch (error) { logPush("audio", error.message); }
  }
  return { volume: volumePercent(settings().volume), available: process.platform === "win32" && !!audioVolumeHelper };
});
app.on("before-quit", () => shutdownSessions());
// Last played (gbox/last_played.py): before this PC's games close with the app (quit, update & relaunch), save each
// one's moment so the web shell's pop-up can offer "Reload with your last moment". Best effort, 7 s at most in all.
let momentsKept = false;
async function keepMoments(limitMs = 7000) {
  if (momentsKept || !FIRST) return;
  momentsKept = true;
  const work = (async () => {
    const s = settings(), auth = { authorization: `Bearer ${await token()}` };
    const r = await fetch(`${s.apiUrl}/api/sessions?include_ended=false`, { headers: auth, signal: AbortSignal.timeout(2500) });
    const mine = (await r.json() || []).filter(x => x.state === "running" && x.detail?.worker_name === s.workerName);
    await Promise.all(mine.map(x => fetch(`${s.apiUrl}/api/sessions/${encodeURIComponent(x.session_id)}/moment?wait=5`,
      { method: "POST", headers: auth, signal: AbortSignal.timeout(limitMs - 500) }).catch(() => null)));
  })().catch(() => {});
  await Promise.race([work, new Promise(r => setTimeout(r, limitMs))]);
}
app.on("will-quit", () => { hotkeys.release(); try { globalShortcut.unregisterAll(); } catch {} });   // no key stays taken

// ---------------- IPC ----------------
ipcMain.handle("settings:get", () => settings());
function saveSettings(s) {
  const next = { ...settings(), ...s };
  if (Object.hasOwn(s, 'recording')) next.recording = recordingExport.preferences(s.recording);
  fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
  fs.writeFileSync(SETTINGS, JSON.stringify(next, null, 1)); settingsStamp = null; cachedToken = null;
  return settings();
}
ipcMain.handle("settings:save", (_e, s) => saveSettings(s));
ipcMain.handle('rec:preferences', () => recordingExport.preferences({ ...RECORDING_DEFAULTS, ...settings().recording }));
ipcMain.handle('rec:preferences-save', (_e, p) => saveSettings({ recording: recordingExport.preferences(p) }).recording);
ipcMain.handle("token", () => token());
ipcMain.handle("settings:reset-token", () => { cachedToken = null; return true; });
// Pick whip pause hold (gbox/pickwhip.py): the renderer pauses the game through POST /api/pickwhip/{sid}/hold. Main
// remembers every hold it forwarded, so a crashed or closed window resumes the game at once instead of waiting for the
// server's lease watchdog (which still covers main itself dying).
const PICK_HOLDS = new Map();                         // sid -> holder
function pickHoldTrack(p, body) {
  const m = /^\/api\/pickwhip\/([^/?]+)\/hold$/.exec(p || ""); if (!m || !body) return;
  const sid = decodeURIComponent(m[1]);
  if (body.op === "pause") PICK_HOLDS.set(sid, body.holder || "app");
  else if (body.op === "release") PICK_HOLDS.delete(sid);
}
function pickHoldReleaseAll(why) {
  for (const [sid, holder] of PICK_HOLDS) {
    logPush("main:log", `pick whip: resuming ${sid} (${why})`);
    api(`/api/pickwhip/${encodeURIComponent(sid)}/hold`, { op: "release", holder }).catch(() => {});
  }
  PICK_HOLDS.clear();
}
ipcMain.handle("api", async (_e, p, body, method) => { try { pickHoldTrack(p, body); return { ok: true, data: await api(p, body, method) }; } catch (e) { return { ok: false, error: e.message }; } });
// a GET whose answer the renderer already holds (same tag) comes back without the data: no copy into the page either
ipcMain.handle("api:tagged", async (_e, p, have) => {
  try {
    const data = await api(p), etag = ETAGS.get(p)?.etag || null;
    return etag && etag === have ? { ok: true, etag, unchanged: true } : { ok: true, etag, data };
  } catch (e) { return { ok: false, error: e.message }; }
});

ipcMain.handle("spark:status", async () => {
  const s = settings();
  const r = await ssh("systemctl is-active gbox.service; mountpoint -q /mnt/gbox/hyperspin && echo mounted || echo unmounted; " +
                      "uptime -p; df -h --output=avail ~ | tail -1; nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null | head -1");
  let health = null;
  try { health = await (await fetch(s.apiUrl + "/api/health", { signal: AbortSignal.timeout(3000) })).json(); } catch {}
  const [service, mount, uptime, free, gpu] = (r.out || "").trim().split("\n");
  return { ssh: r.ok || !!r.out, service, mount, uptime, free: free?.trim(), gpu, api: !!health, error: r.ok ? null : r.err };
});

ipcMain.handle("spark:action", async (_e, action) => {
  const s = settings();
  const cmds = {
    install: `cd ${s.repoRemote} && sed -i 's/\\r$//' scripts/bootstrap-linux.sh && bash scripts/bootstrap-linux.sh`,
    update: `cd ${s.repoRemote} && (if [ -d .git ]; then git pull --ff-only; else echo "not a git checkout: skipping pull"; fi) && bash scripts/bootstrap-linux.sh`,
    start: "sudo -n systemctl start gbox.service && systemctl is-active gbox.service",
    stop: "sudo -n systemctl stop gbox.service; systemctl is-active gbox.service",
    restart: "sudo -n systemctl restart gbox.service && sleep 2 && systemctl is-active gbox.service",
    setup: `cd ${s.repoRemote} && .venv-linux-$(uname -m)/bin/python -m gbox --config gbox.toml setup`,
    test: `cd ${s.repoRemote} && .venv-linux-$(uname -m)/bin/python -m pytest -q -p no:cacheprovider`,
    logs: "journalctl -u gbox.service -n 200 -f --no-pager -o cat",
  };
  if (!cmds[action]) throw new Error("unknown action " + action);
  const id = `spark-${action}`;
  if (procs.has(id)) return id;
  stream(id, "ssh", ["-o", "BatchMode=yes", "-tt", s.sshHost, cmds[action]]);
  return id;
});

ipcMain.handle("task:snapshot", () => [...taskLogs.values()].map(task => ({ ...task })));
ipcMain.handle("task:cancel", (_e, id) => {
  if (id === "recording" && rec) {
    const r = rec; rec = null;
    r.out.end(() => fs.unlink(r.file, () => {}));
    send("recording-cancelled");
    send("task", id, "\nRecording cancelled.\n"); taskDone(id, 1);
    return true;
  }
  const p = procs.get(id);
  if (!p) return false;
  if (process.platform === "win32" && p.pid) execFile("taskkill", ["/T", "/F", "/PID", String(p.pid)], { windowsHide: true }, () => {});
  else p.kill();
  return true;
});

ipcMain.handle("win:setup", () => {
  const s = settings();
  const id = "win-setup";
  if (!procs.has(id))
    stream(id, "powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(s.repoLocal, "scripts", "bootstrap-windows.ps1"), "-Repo", s.repoLocal]);
  return id;
});

// The last worker exit, so the app can say WHY this PC's worker is offline (#1296).
let workerTail = "", workerLastExit = null, workerStarting = null;
function workerExitReason(text) {
  const lines = String(text).split(/\r?\n/).map(l => l.replace(/^\d\d:\d\d:\d\d\.\d+ \[win-worker\]\s*/, "").trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--)
    if (/^[A-Za-z_.]*(Error|Exception)\b.*:/.test(lines[i])) return lines[i].slice(0, 600);
  return lines.slice(-1)[0]?.slice(0, 600) || "";
}
async function startWorker(options = {}) {
  if (clientHandoffBusy) return { running: !!worker, started: false, error: 'Desktop refresh is in progress.' };
  if (worker) return { running: true, started: false };
  if (workerStarting) return workerStarting;
  workerStarting = startWorkerInner(options);
  try { return await workerStarting; } finally { workerStarting = null; }
}
async function startWorkerInner(options) {
  const s = settings();
  const controlSecret = clientHandoff.nonce();
  if (worker) return { running: true };
  if (!fs.existsSync(venvPython())) return { running: false, error: "Windows node not installed yet — run 'Install / update Windows node'" };
  if (STANDALONE) {                                   // this PC is the whole gBox: control plane + worker in one process
    const cfg = path.join(s.repoLocal, "gbox.toml");
    worker = spawn(venvPython(), ["-P", "-m", "gbox", "--config", cfg, "serve", "--worker"],
      { env: { ...process.env, PYTHONPATH: s.repoLocal, GBOX_CONFIG: cfg, PYTHONUNBUFFERED: "1" }, cwd: s.repoLocal, windowsHide: true });
  } else {
    const t = await token();
    if (!t) return { running: false, error: "no API token: paste it in Settings, or make the Spark share / SSH reachable" };
    const args = ["-P", "-m", "gbox", "--config", path.join(s.repoLocal, "gbox.toml"), "worker", "--server", s.apiUrl, "--name", s.workerName];
    if (options.reconcileResults) args.push("--reconcile-results");
    worker = spawn(venvPython(), args,
      { env: { ...process.env, PYTHONPATH: s.repoLocal, GBOX_TOKEN: t, PYTHONUNBUFFERED: "1", GBOX_CLIENT_CONTROL: controlSecret }, cwd: os.homedir(), windowsHide: true });
  }
  const thisWorker = worker;
  const control = STANDALONE ? null : clientHandoff.workerChannel(thisWorker, controlSecret);
  workerControl = control;
  workerTail = "";
  const out = d => { const t = d.toString(); workerTail = (workerTail + t).slice(-8000); send("task", "win-worker", t); };
  worker.stdout.on("data", d => { const text = control ? control.feed(d) : d; if (text.length) out(text); }); worker.stderr.on("data", out);
  worker.on("close", code => {
    workerLastExit = { code, at: Date.now(), reason: workerExitReason(workerTail) };
    send("task", "win-worker", `\n[worker exited ${code}]\n`);
    if (worker === thisWorker) { worker = null; workerControl = null; } send("worker", false);
    if (!workerStopRequested && settings().autoStartWorker) setTimeout(startWorker, 5000);   // watchdog
    workerStopRequested = false;
  });
  send("worker", true);
  return { running: true, started: true };
}
// Reconnect only a stopped worker. A stale heartbeat never authorizes killing
// the existing worker or any native children it owns.
async function restartWorker() {
  if (worker) {
    return { running: true, started: false, error: "This PC's worker is still running. Reconnect is held; no worker or game was stopped." };
  }
  if (workerStarting) return { running: false, started: false, error: "This PC's worker is already starting. Wait for its status; no processes were stopped." };
  if (STANDALONE) return { running: false, started: false, error: "Standalone control-plane recovery requires a separate maintenance review; no service was restarted." };
  const r = await startWorker({ reconcileResults: true });
  return { ...r, restarted: r.started === true, lastExit: workerLastExit };
}
ipcMain.handle("win:worker", (_e, op) => {
  if (op === "start") return startWorker();
  if (op === "stop" && worker) { workerStopRequested = true; execFile("taskkill", ["/T", "/F", "/PID", String(worker.pid)]); return { running: false }; }
  if (op === "restart") return restartWorker();
  return { running: !!worker, lastExit: workerLastExit };
});

ipcMain.handle("pad:devices", () => new Promise(resolve => {
  if (process.platform !== "win32") return resolve([]);
  execFile(venvPython(), ["-P", "-m", "gbox.gamepads"],
    { windowsHide: true, timeout: 5000, env: { ...process.env, PYTHONPATH: settings().repoLocal } }, (error, stdout) => {
    if (error) return resolve([]);
    try { resolve(JSON.parse(stdout.trim())); } catch { resolve([]); }
  });
}));

let padWatcher = null;
function startPadWatcher() {
  if (process.platform !== "win32" || padWatcher) return;
  const child = spawn(venvPython(), ["-u", "-P", "-m", "gbox.gamepads", "--watch"],
    { windowsHide: true, env: { ...process.env, PYTHONPATH: settings().repoLocal } });
  padWatcher = child;
  let buffer = "";
  child.stdout.on("data", chunk => {
    buffer += chunk.toString();
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      try { if (win && !win.isDestroyed()) win.webContents.send("pad-state", JSON.parse(line)); } catch {}
    }
  });
  child.on("error", () => {});
  child.on("close", () => { if (padWatcher === child) padWatcher = null; if (!app.isQuitting) setTimeout(startPadWatcher, 3000); });
}

ipcMain.handle("open:external", (_e, url) => shell.openExternal(url));
// #1639 the download icon on the Mods cards / Builds rows: Export… picks a folder on this PC (the export job runs on this
// PC's worker and writes there); Show in folder / Open folder open Explorer. Folders only: never runs a file.
ipcMain.handle("dialog:folder", async (_e, o = {}) => {
  const start = typeof o.defaultPath === "string" && o.defaultPath && fs.existsSync(o.defaultPath) ? o.defaultPath : undefined;
  const r = await dialog.showOpenDialog(win, { title: String(o.title || "Choose a folder").slice(0, 200), defaultPath: start,
    buttonLabel: "Export here", properties: ["openDirectory", "createDirectory", "promptToCreate", "dontAddToRecent"] });
  return r.canceled ? "" : (r.filePaths[0] || "");
});
ipcMain.handle("shell:show", (_e, p) => {
  if (typeof p !== "string" || !p || !fs.existsSync(p)) return false;
  shell.showItemInFolder(path.normalize(p)); return true;
});
ipcMain.handle("shell:open", async (_e, p) => {
  if (typeof p !== "string" || !p) return false;
  try { if (!fs.statSync(p).isDirectory()) return false; } catch { return false; }
  return (await shell.openPath(path.normalize(p))) === "";
});
// a finished build (the embedded view's bell tray, gbox/build_notify.py): an OS notification while gBox is not in front;
// a click brings the window back with the tray open. Kept referenced until closed (a collected one loses its click).
const OS_NOTES = new Set();
ipcMain.handle("notify:os", (_e, n = {}) => {
  if (!Notification.isSupported() || (win && win.isVisible() && win.isFocused() && !win.isMinimized())) return false;
  const note = new Notification({ title: String(n.title || "gBox").slice(0, 120), body: String(n.body || "").slice(0, 240) });
  OS_NOTES.add(note);
  note.on("click", () => { OS_NOTES.delete(note); if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); win.webContents.send("notify:click", n.id || ""); } });
  note.on("close", () => OS_NOTES.delete(note));
  note.show();
  return true;
});

ipcMain.handle("report:clipboard-files", async () => {
  if (process.platform !== "win32") return [];
  // Explorer's copied files use CF_HDROP, which Chromium's paste event does not always expose.
  const paths = await new Promise((resolve, reject) => {
    execFile("powershell.exe", ["-NoProfile", "-STA", "-Command",
      "Add-Type -AssemblyName System.Windows.Forms; $OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); ConvertTo-Json -Compress -InputObject @([System.Windows.Forms.Clipboard]::GetFileDropList())"],
      { windowsHide: true, encoding: "utf8", timeout: 10000 }, (error, stdout) => {
        if (error) return reject(new Error("Cannot read copied files: " + error.message));
        try { resolve(JSON.parse(stdout.replace(/^\uFEFF/, "").trim() || "[]")); } catch { reject(new Error("Cannot read copied files")); }
      });
  });
  if (paths.length > 18) throw new Error("Attach up to 18 files per report");
  return Promise.all(paths.map(async file => {
    const stat = await fs.promises.stat(file);
    if (!stat.isFile()) throw new Error(`Copy individual files, rather than folders: ${path.basename(file)}`);
    const data = await fs.promises.readFile(file), ext = path.extname(file).toLowerCase();
    const type = ({ ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
                    ".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf" })[ext] || "application/octet-stream";
    return { name: path.basename(file), type, b64: data.toString("base64") };
  }));
});

// Screen recording: the renderer records this window (MediaRecorder, H.264 MP4) and streams 1 s chunks here,
// appended straight to disk so long sessions never sit in memory.
const REC_DIR = path.join(process.env.LOCALAPPDATA || app.getPath("videos"), "gbox", "recordings");
let rec = null;
function recordingCrop(rect, display) {
  const d = display || screen.getDisplayMatching(win.getBounds()), k = d.scaleFactor;
  let b = win.getBounds();
  if (rect) {
    if (![rect.x, rect.y, rect.w, rect.h].every(Number.isFinite) || rect.w < 2 || rect.h < 2) throw new Error("No visible gameplay to record");
    const content = win.getContentBounds(), zoom = win.webContents.getZoomFactor();
    b = { x: content.x + rect.x * zoom, y: content.y + rect.y * zoom, width: rect.w * zoom, height: rect.h * zoom };
  }
  const x = Math.max(b.x, d.bounds.x), y = Math.max(b.y, d.bounds.y);
  const w = Math.min(b.x + b.width, d.bounds.x + d.bounds.width) - x;
  const h = Math.min(b.y + b.height, d.bounds.y + d.bounds.height) - y;
  if (w < 2 || h < 2) throw new Error("The recording moved off its captured display");
  return { x: Math.round((x - d.bounds.x) * k), y: Math.round((y - d.bounds.y) * k), w: Math.round(w * k), h: Math.round(h * k),
           sw: Math.round(d.bounds.width * k), sh: Math.round(d.bounds.height * k) };
}
ipcMain.handle("rec:start", (_e, ext, rect) => {
  if (clientHandoffBusy) throw Error('Desktop refresh is in progress.');
  if (rec) throw new Error("A recording is already running");
  if (!["mp4", "webm"].includes(ext)) throw new Error("Unsupported recording format");
  const d = screen.getDisplayMatching(win.getBounds()), crop = recordingCrop(rect, d);
  fs.mkdirSync(REC_DIR, { recursive: true });
  const file = path.join(REC_DIR, `gbox-${new Date().toISOString().replace(/[:.]/g, "-")}.${ext}`);
  rec = { file, out: fs.createWriteStream(file), bytes: 0, display: d };
  taskLogs.set("recording", { id: "recording", started: Date.now() / 1000, state: "running", output: `Recording ${path.basename(file)}\n`, bytes: 0 });
  // record the SCREEN gBox is on, cropped to the window: window capture leaves the docked GPU game window black
  return { sourceId: win.getMediaSourceId(), screenId: `screen:${d.id}:0`, displayId: String(d.id), crop, file };
});
ipcMain.handle("rec:crop", (_e, rect) => recordingCrop(rect, rec?.display));
ipcMain.handle("rec:screens", async () => (await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 0, height: 0 } }))
  .map(x => ({ id: x.id, display_id: x.display_id })));
ipcMain.handle("rec:chunk", (_e, buf) => { if (rec) { rec.out.write(Buffer.from(buf)); rec.bytes += buf.byteLength;
  const task = taskLogs.get("recording"); if (task) task.bytes = rec.bytes; } return rec ? rec.bytes : 0; });
ipcMain.handle("rec:stop", () => new Promise(res => {
  if (!rec) return res(null);
  const r = rec; rec = null;
  r.out.end(() => { send("task", "recording", `Finished: ${r.bytes} bytes\n`); taskDone("recording", 0); res({ file: r.file, bytes: r.bytes }); });
}));
ipcMain.handle("rec:abort", () => new Promise(resolve => {
  if (!rec) return resolve();
  const r = rec; rec = null;
  r.out.end(() => { fs.unlink(r.file, () => { send("task", "recording", "Recording aborted.\n"); taskDone("recording", 1); resolve(); }); });
}));
// Size-capped recordings: a file over the target is re-encoded to fit (bitrate from the duration, resolution stepped down
// as the bitrate drops so it stays sharp). HandBrakeCLI (winget HandBrake.HandBrake.CLI) does it; ffmpeg if it's missing.
function findExe(name) {
  const pk = path.join(process.env.LOCALAPPDATA || "", "Microsoft", "WinGet", "Packages");
  const c = [];
  try { for (const d of fs.readdirSync(pk)) { c.push(path.join(pk, d, name)); try { for (const s of fs.readdirSync(path.join(pk, d))) c.push(path.join(pk, d, s, "bin", name)); } catch {} } } catch {}
  for (const d of (process.env.PATH || "").split(path.delimiter)) c.push(path.join(d, name));
  return c.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } }) || null;
}
const runExe = (exe, args) => new Promise((res, rej) => {
  if (clientHandoffBusy) return rej(Error('Desktop refresh is in progress.'));
  const p = spawn(exe, args, { windowsHide: true }); let err = "";
  procs.set("rec-fit", p);
  taskLogs.set("rec-fit", { id: "rec-fit", pid: p.pid, started: Date.now() / 1000, state: "running", output: "" });
  p.stderr.on("data", d => { err = (err + d).slice(-2000); send("task", "rec-fit", String(d)); });
  p.stdout.on("data", d => send("task", "rec-fit", String(d)));
  p.on("error", e => { err = e.message; send("task", "rec-fit", `[error] ${e.message}\n`); });
  p.on("close", code => { procs.delete("rec-fit"); taskDone("rec-fit", code);
    code === 0 ? res() : rej(new Error(`${path.basename(exe)} exit ${code}: ${err.split("\n").slice(-3).join(" ")}`)); });
});
let recFitBusy = false;
ipcMain.handle("rec:fit", async (_e, file, options) => {
  if (recFitBusy) throw Error('Another recording is being processed; this original is still saved locally');
  recFitBusy = true;
  let temporary;
  try {
  file = await recordingExport.ownedOriginal(file, REC_DIR);
  const o = recordingExport.preferences({ ...RECORDING_DEFAULTS, ...settings().recording, ...options });
  const originalStamp = await recordingExport.fingerprint(file);
  const target = o.targetMB * 1048576, size = fs.statSync(file).size;
  const finish = candidate => recordingExport.finish({ original: file, candidate, exportDir: o.exportDir, keep: o.keep, originalStamp });
  if (!target || size <= target) return { ...await finish(file), bytes: size, compressed: false };
  const dur = Math.max(1, Number.isFinite(options?.seconds) ? options.seconds : 1), preset = { fast: "veryfast", balanced: "medium", best: "slow" }[o.speed] || "medium";
  const hb = findExe("HandBrakeCLI.exe"), ff = findExe("ffmpeg.exe");
  if (!hb && !ff) throw new Error("neither HandBrakeCLI nor ffmpeg is installed (winget install HandBrake.HandBrake.CLI)");
  const audioKbps = 128;
  let kbps = Math.max(120, Math.floor(target * 8 * 0.92 / 1000 / dur) - audioKbps);
  for (let attempt = 0; attempt < 3; attempt++) {
    const h = kbps >= 3500 ? 1080 : kbps >= 1800 ? 720 : kbps >= 900 ? 540 : kbps >= 450 ? 360 : 240, fps = kbps < 900 ? 30 : 60;
    const out = temporary = path.join(REC_DIR, `.gbox-fit-${require('crypto').randomUUID()}.mp4`);
    send("task", "rec", `compressing ${path.basename(file)} to ≤${o.targetMB} MB: ${kbps} kbps, ${h}p, ${fps} fps (${hb ? "HandBrake" : "ffmpeg"})\n`);
    if (hb) await runExe(hb, ["-i", file, "-o", out, "-e", "x264", "--encoder-preset", preset, "-b", String(kbps), "--multi-pass", "--turbo",
                              "--maxHeight", String(h), "-r", String(fps), "--pfr", "-a", "1", "-E", "av_aac", "-B", String(audioKbps), "-O"]);
    else await runExe(ff, ["-y", "-i", file, "-map", "0:v:0", "-map", "0:a:0?", "-c:a", "aac", "-b:a", `${audioKbps}k`, "-vf", `scale=-2:'min(${h},ih)'`, "-r", String(fps), "-c:v", "libx264", "-preset", preset,
                           "-b:v", `${kbps}k`, "-maxrate", `${kbps}k`, "-bufsize", `${kbps * 2}k`, "-movflags", "+faststart", out]);
    const got = fs.statSync(out).size;
    if (!got) throw Error('The encoder produced an empty recording; original retained');
    if (got > 0 && got <= target) {
      const name = path.basename(file).replace(/\.(mp4|webm)$/i, '') + `-${o.targetMB}MB.mp4`;
      const local = await recordingExport.publish(out, REC_DIR, name);
      return { ...await finish(local), bytes: got, compressed: true, original: size, kbps, height: h, tool: hb ? "HandBrake" : "ffmpeg" };
    }
    fs.unlinkSync(out); kbps = Math.max(80, Math.floor(kbps * target / got * 0.9));   // overshot: aim lower and retry
  }
  throw new Error(`couldn't get ${path.basename(file)} under ${o.targetMB} MB`);
  } finally {
    if (temporary) await fs.promises.unlink(temporary).catch(() => {});
    recFitBusy = false;
  }
});
// Replay export uses this desktop profile's current folder, never a browser download directory.
ipcMain.handle('rec:save-clip', async (_e, clip) => {
  const o = recordingExport.preferences({ ...RECORDING_DEFAULTS, ...settings().recording });
  return recordingExport.saveReplay({ clip, directory: REC_DIR, exportDir: o.exportDir,
    fetchArtifact: async sha => fetch(settings().apiUrl + '/api/artifacts/' + sha, {
      headers: { authorization: `Bearer ${await token()}` }, redirect: 'error', signal: AbortSignal.timeout(120000),
    }) });
});
// chat export: printable HTML -> PDF (Save dialog); a PNG data URL -> the system clipboard as an image
ipcMain.handle("export:pdf", async (_e, html, name) => {
  const w = new BrowserWindow({ show: false, webPreferences: { offscreen: true } });
  try {
    await w.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
    const pdf = await w.webContents.printToPDF({ printBackground: true, margins: { marginType: "default" } });
    const r = await dialog.showSaveDialog(win, { defaultPath: name || "conversation.pdf", filters: [{ name: "PDF", extensions: ["pdf"] }] });
    if (r.canceled || !r.filePath) return null;
    fs.writeFileSync(r.filePath, pdf); return r.filePath;
  } finally { w.destroy(); }
});
// Esc / F11 / Alt+Enter always leave full screen, wherever the keyboard focus is (the library/stream view is a <webview>,
// whose keys never reach the page that owns the window); F11 / Alt+Enter also enter it.
app.on("web-contents-created", (_e, wc) => wc.on("before-input-event", (ev, input) => {
  if (!win) return;
  if (input.code === "Backquote" && !input.control && !input.alt) {      // hold ~ = push-to-talk (released = send)
    if (!(input.type === "keyDown" && input.isAutoRepeat)) win.webContents.send("ptt", input.type === "keyDown");
    ev.preventDefault(); return;
  }
  if (input.type !== "keyDown") return;
  const toggle = input.key === "F11" || (input.alt && input.key === "Enter");
  if (input.key === "Escape" && compactWindow.state().on) {
    // Shell fields (notably the coach) own Escape. Their guarded DOM handler restores only outside text entry.
    if (wc !== win.webContents) { compactWindow.restore().catch(error => logPush('compact', error.message)); ev.preventDefault(); }
  }
  else if (input.key === "Escape" && win.isFullScreen()) { win.setFullScreen(false); win.webContents.send("fullscreen", false); ev.preventDefault(); }
  else if (toggle) { win.webContents.send("hotkey", "fullscreen"); ev.preventDefault(); }   // the page's view mode follows
  else if (input.key === "F2" && (input.shift || input.control) && !input.alt) { win.webContents.send("hotkey", input.shift ? "slot+" : "slot-"); ev.preventDefault(); }
  else if (GAME_KEYS[input.key] && !input.control && !input.alt && !input.shift) { win.webContents.send("hotkey", GAME_KEYS[input.key]); ev.preventDefault(); }
}));
// Universal game hotkeys, the same for every emulator: F2 save state, F4 load state, F3 autoplay on/off.
// Inside gBox (any page, the streamed view included) they arrive here; while a native game window has the keyboard they come
// through global shortcuts, held only while a game is docked AND gBox is the foreground window (see f3(), hotkey-scope.js).
const GAME_KEYS = { F2: "save", F3: "autoplay", F4: "load", F5: "client-refresh" }; // F5 reloads only the client
ipcMain.handle("win:fullscreen", (_e, on) => { win.setFullScreen(!!on); return win.isFullScreen(); });
ipcMain.handle("clip:image", (_e, dataUrl) => { clipboard.writeImage(nativeImage.createFromDataURL(dataUrl)); return true; });
ipcMain.handle("rec:open", (_e, file) => file ? shell.showItemInFolder(file) : shell.openPath(REC_DIR));

// ---------------- native game windows embedded in the app (Windows) ----------------
let embedder = null, embedQ = [], embedBuf = "";
function embedCmd(cmd) {
  if (process.platform !== "win32") return Promise.resolve({ ok: false });
  if (!embedder) {
    embedder = spawn(venvPython(), ["-u", path.join(__dirname, "winembed.py")], { windowsHide: true });
    embedder.stdout.on("data", d => { embedBuf += d; let i; while ((i = embedBuf.indexOf("\n")) >= 0) { const l = embedBuf.slice(0, i); embedBuf = embedBuf.slice(i + 1); const m = JSON.parse(l);
      if (m.event === "whip") { pickWhip(m); continue; }
      if (m.event === "foreground") { hotkeys.setFront(!!m.front); continue; }   // gBox gained / lost the foreground
      if (m.event === 'piprestore') { compactWindow.restore().catch(error => logPush('compact', error.message)); continue; }
      if (m.event) { if (win) { const k = screen.getDisplayMatching(win.getBounds()).scaleFactor; win.webContents.send("embed:event", { ...m, x: m.x / k, y: m.y / k }); } continue; }
      const r = embedQ.shift(); r && r(m); } });
    embedder.on("close", () => { embedder = null; embedded = null; fgWatched = 0; hotkeys.setFront(false); embedQ.splice(0).forEach(r => r({ ok: false }));
      if (!quitting && compactWindow.state().on && !compactRecoveryPending) {
        compactRecoveryPending = true;
        compactWindow.restore().catch(error => logPush('compact', error.message));
      } });
  }
  return new Promise(res => { embedQ.push(res); embedder.stdin.write(JSON.stringify(cmd) + "\n"); });
}
let compactChromeBits = null, compactRecoveryPending = false;
let clientReloading = false;
const compactWindow = require('./compact-window.cjs').create({ getWin: () => win, screen,
  nativeChrome: async on => {
    if (!win || win.isDestroyed()) return { ok: false, error: 'The gBox window is unavailable.' };
    if (process.platform !== 'win32') { win.setWindowButtonVisibility?.(!on); return { ok: true }; }
    const appWindow = Number(win.getNativeWindowHandle().readBigUInt64LE(0));
    const watched = await embedCmd({ op: 'watch', app: appWindow });
    if (!watched.ok) return watched;
    const result = await embedCmd({ op: 'appchrome', app: appWindow, pid: process.pid, on,
      ...(!on && compactChromeBits !== null ? { bits: compactChromeBits } : {}) });
    if (result.ok) { compactChromeBits = on ? result.bits : null; compactRecoveryPending = false; }
    return result;
  },
  emit: state => { if (win && !win.isDestroyed()) win.webContents.send('compact:view', state); }
});
ipcMain.handle('compact:view', (event, state) => {
  if (!win || event.sender !== win.webContents || (event.senderFrame && event.senderFrame !== win.webContents.mainFrame)) throw Error('Only the gBox app can change picture-in-picture mode.');
  return compactWindow.update(state);
});
async function inspectClientIdle() {
  if (STANDALONE) return 'This desktop also hosts its control plane; a client-only restart is unavailable.';
  if (startupHandoff?.error) return startupHandoff.error;
  if (workerStarting) return 'The local worker is still starting.';
  if (procs.size || rec || recFitBusy) return 'This desktop still has an active task or recording.';
  if (embedded || embedSyncPending) return 'A native game or pending game-window operation still belongs to this desktop.';
  const local = settings();
  const disk = await new Promise((resolve, reject) => execFile(venvPython(),
    ['-P', '-m', 'gbox.worker_client_control', '--inspect', path.join(local.repoLocal, 'gbox.toml')],
    { windowsHide: true, timeout: 6000, env: { ...process.env, PYTHONPATH: local.repoLocal } }, (error, out) => {
      if (error) return reject(Error('Local game ownership could not be verified.'));
      try { const value = JSON.parse(out); if (typeof value.runtime !== 'string' || !path.isAbsolute(value.runtime)) throw Error(); resolve(value); }
      catch { reject(Error('Local game ownership could not be verified.')); }
    }));
  if (disk.reason) return disk.reason;
  const workerPid = worker?.pid || 0;
  const script = `$ErrorActionPreference='Stop'; $items=@(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne ${process.pid} -and $_.ProcessId -ne ${workerPid} -and (
    ($_.ExecutablePath -and ($_.ExecutablePath -like '*\\gBox\\runtime\\*' -or $_.ExecutablePath.StartsWith(${psq(disk.runtime + path.sep)}, [StringComparison]::OrdinalIgnoreCase))) -or
    ($_.CommandLine -and $_.CommandLine -match '-m gbox .*\\bworker\\b')) } | Select-Object ProcessId,Name);
    ConvertTo-Json -InputObject $items -Compress`;
  const found = await new Promise((resolve, reject) => execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
    { windowsHide: true, timeout: 6000 }, (error, out) => {
      if (error) return reject(Error('Local process activity could not be verified.'));
      try { const value = JSON.parse(out); if (!Array.isArray(value)) throw Error(); resolve(value); }
      catch { reject(Error('Local process activity could not be verified.')); }
    }));
  if (found.length) return 'Another local game or worker is still running.';
  // Recheck after the asynchronous process inventory. New work is gated while this runs.
  if (procs.size || rec || recFitBusy || embedded || embedSyncPending || workerStarting) return 'Local activity changed during the desktop refresh check.';
  return null;
}
function assertClientSender(event) {
  if (!win || event.sender !== win.webContents || (event.senderFrame && event.senderFrame !== win.webContents.mainFrame)) throw Error('Only the gBox app can reload its client.');
}
ipcMain.handle('client:reload', async (event, state) => {
  assertClientSender(event);
  if (clientReloading) return false;
  clientReloading = true;
  try {
    const version = await clientVersions?.read();
    if (version?.restart) {
      const hadWorker = !!worker;
      if (!state || state.v !== 1) clientActivation = { state: 'pending', reason: 'The saved stream view is unavailable; refreshed views only.' };
      else clientActivation = await clientHandoff.perform({
        lock: value => { clientHandoffBusy = value; workerStopRequested = value; },
        inspect: inspectClientIdle,
        stopWorker: async () => {
          if (!worker) return false;
          if (!workerControl) throw Error('The running local worker does not support safe desktop refresh yet.');
          await workerControl.stop(); return true;
        },
        save: value => clientHandoff.save(CLIENT_HANDOFF_FILE, { state: value, ...compactWindow.handoff(),
          mini: mini && !mini.isDestroyed() ? { ...miniSession, bounds: mini.getBounds() } : pendingMini,
          startWorker: hadWorker || settings().autoStartWorker }),
        launch: id => {
          app.relaunch({ args: [...process.argv.slice(1).filter(a => !a.startsWith(clientHandoff.ARG)), clientHandoff.ARG + id] });
          clientRefreshExit = true;
          setTimeout(() => { shutdownSessions(); app.exit(0); }, 100);
        },
        resumeWorker: async () => { if (!worker && hadWorker) await startWorker(); }
      }, state);
      clientActivation.pid = process.pid;
      if (clientActivation.state === 'relaunching') return clientActivation;
    }
  } catch (error) { clientActivation = { state: 'pending', pid: process.pid, reason: String(error.message || error) }; }
  try { if (mini && !mini.isDestroyed()) mini.webContents.reloadIgnoringCache(); } catch {} // keep its session URL and bounds
  win.webContents.reloadIgnoringCache();
  return clientActivation;
});
let clientVersions = null;
ipcMain.handle('client:version', async event => {
  if (!win || event.sender !== win.webContents || (event.senderFrame && event.senderFrame !== win.webContents.mainFrame)) throw Error('Only the gBox app can inspect its client version.');
  return { ...await clientVersions?.read(), activation: clientActivation };
});
ipcMain.handle('client:handoff', event => { assertClientSender(event); return handoffView; });
ipcMain.handle('client:handoff-saved', event => { assertClientSender(event); handoffView = null; return true; });
function saveClientView(state = savedClientState, server = savedClientOrigin) {
  if (!state || state.v !== 1 || !win || win.isDestroyed()) return false;
  const origin = clientViews.origin(server);
  if (!origin || origin !== clientViews.origin(settings().apiUrl)) return false;
  const value = clientViews.view({ state, ...compactWindow.handoff(),
    mini: mini && !mini.isDestroyed() ? { ...miniSession, bounds: mini.getBounds() } : pendingMini }, 0);
  const key = JSON.stringify({ origin, ...value });
  if (key !== savedClientKey) clientViewStore.save(origin, value);
  savedClientState = value.state; savedClientOrigin = origin; savedClientKey = key;
  return true;
}
function queueClientView() {
  clearTimeout(clientViewTimer);
  clientViewTimer = setTimeout(() => { try { saveClientView(); } catch (error) { logPush('saved-view', error.message); } }, 300);
}
ipcMain.handle('client:view', event => { assertClientSender(event); return clientViewStore.load(settings().apiUrl)?.state || null; });
ipcMain.handle('client:view-save', (event, state, origin) => { assertClientSender(event); return saveClientView(state, origin); });
let embedded = null, gpuSurface = false;                          // active presentation uses Chromium's compositor
// Pick whip: Alt + drag over the game draws a line from one thing to another; on release the frame (with the line) goes
// to the chat as "swap this with that". The line lives on a transparent click-through window above the docked game.
let whipOv = null, whip = null;
const WHIP_HTML = `<html><body style="margin:0;background:transparent;overflow:hidden"><canvas id="c" style="position:fixed;inset:0"></canvas><script>
const c = document.getElementById("c"), g = c.getContext("2d"); const fit = () => { c.width = innerWidth; c.height = innerHeight; }; fit(); onresize = fit;
window.L = (ax, ay, bx, by) => { g.clearRect(0, 0, c.width, c.height); g.lineCap = "round"; g.shadowColor = "#000"; g.shadowBlur = 6;
  g.strokeStyle = "#ff3b3b"; g.lineWidth = 4; g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke();
  const a = Math.atan2(by - ay, bx - ax), h = 18; g.beginPath(); g.moveTo(bx - 14 * Math.cos(a), by - 14 * Math.sin(a));
  g.lineTo(bx - (14 + h) * Math.cos(a - .4), by - (14 + h) * Math.sin(a - .4)); g.moveTo(bx - 14 * Math.cos(a), by - 14 * Math.sin(a));
  g.lineTo(bx - (14 + h) * Math.cos(a + .4), by - (14 + h) * Math.sin(a + .4)); g.stroke();
  g.lineWidth = 3; for (const [x, y] of [[ax, ay], [bx, by]]) { g.beginPath(); g.arc(x, y, 12, 0, 7); g.stroke(); } };
<\/script></body></html>`;
async function pickWhip(m) {
  if (!win) return;
  const k = screen.getDisplayMatching(win.getBounds()).scaleFactor, cb = win.getContentBounds(), x = m.x / k, y = m.y / k;
  if (gpuSurface) {
    if (whipOv && !whipOv.isDestroyed()) whipOv.hide();
    whip = null;
    win.webContents.send("embed:event", { ...m, event: "gpu-whip", x, y });
    return;
  }
  if (m.phase === "start") {
    if (!whipOv) {
      whipOv = new BrowserWindow({ parent: win, frame: false, transparent: true, show: false, focusable: false, skipTaskbar: true,
                                   resizable: false, movable: false, hasShadow: false, webPreferences: { backgroundThrottling: false } });
      whipOv.setIgnoreMouseEvents(true);
      await whipOv.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(WHIP_HTML));
    }
    whipOv.setBounds(cb); whipOv.showInactive();
    whip = { ax: x, ay: y, bx: x, by: y };
  }
  if (!whip) return;
  whip.bx = x; whip.by = y;
  whipOv.webContents.executeJavaScript(`L(${whip.ax},${whip.ay},${whip.bx},${whip.by})`).catch(() => {});
  if (m.phase !== "end") return;
  const w = whip; whip = null;
  if (Math.hypot(w.bx - w.ax, w.by - w.ay) < 12) { whipOv.hide(); OV.pick(w.ax, w.ay); return; }   // a plain Alt+click: marks the overlay swap's target, if it waits for one
  await new Promise(r => setTimeout(r, 60));                    // the last line segment is on screen
  const shot = await osShot().catch(() => null);
  whipOv.hide();
  win.webContents.send("embed:event", { event: "whip", phase: "end", a: [w.ax, w.ay], b: [w.bx, w.by], shot });
}
// Overlay swap (overlay.js): a collection model tracked over the player's character in the docked game, any game
const OV = require("./overlay")({ app, ipcMain, BrowserWindow, getWin: () => win, venvPython, settings, token, send });
// F3 = autoplay while a game is docked: the game window owns the keyboard, so it has to be a global shortcut.
// F2 save · Shift/Ctrl+F2 slot ± · F4 load · Alt+Enter / F11 = full screen on/off (the docked game owns the keyboard, so
// without these there is no way out of full screen from inside the game; Esc stays the game's own key).
// Scoped to gBox: held only while a game is docked AND gBox (or the game docked in it) is the foreground window. Any other
// application in front (Blender: F2 rename, F3 search, Ctrl+I invert, F11...) gets its keys; nothing is registered then.
const hotkeys = require("./hotkey-scope")({ globalShortcut, onKey: a => win && win.webContents.send("hotkey", a),
  keys: { ...GAME_KEYS, "Shift+F2": "slot+", "CommandOrControl+F2": "slot-", "CommandOrControl+I": "eyedropper",
          "Alt+Enter": "fullscreen", "F11": "fullscreen" } });
let fgWatched = 0;                                               // the gBox HWND winembed.py reports the foreground for
const appHwnd = () => win && !win.isDestroyed() ? Number(win.getNativeWindowHandle().readBigUInt64LE(0)) : 0;
// Ask winembed.py whether gBox is in front now (and have it report every change from then on). Only for a docked game,
// which runs the helper anyway; with no answer the hotkeys stay released.
async function checkFront() {
  const hwnd = appHwnd();
  if (!hwnd || process.platform !== "win32") return hotkeys.setFront(false);
  fgWatched = hwnd;
  const r = await embedCmd({ op: "watch", app: hwnd }).catch(() => null);
  if (!(r && r.ok)) fgWatched = 0;
  return hotkeys.setFront(!!(r && r.ok && r.front));
}
function f3(on) {
  hotkeys.setDocked(on);
  if (on && appHwnd() !== fgWatched) checkFront();
}
let embedSyncQueue = Promise.resolve(), embedSyncPending = 0;
const syncGameSurface = require("./game-surface-main")({ getWin: () => win, embedCmd,
  nativeSync: st => { gpuSurface = false; return syncEmbeddedGame(st); }, f3,
  frameDir: GAME_FRAME_DIR, onCapture: pid => { embedded = pid; gpuSurface = true; },
  publishFrame: async (sid, png) => {
    const r = await fetch(settings().apiUrl + `/api/sessions/${encodeURIComponent(sid)}/frame`, {
      method: "POST", headers: { authorization: `Bearer ${await token()}`, "content-type": "image/jpeg" },
      body: nativeImage.createFromBuffer(png).toJPEG(90), signal: AbortSignal.timeout(3000) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } });
ipcMain.handle("embed:sync", (_e, st) => {
  if (clientHandoffBusy) return { ok: false, error: 'Desktop refresh is in progress.' };
  embedSyncPending++;
  const next = embedSyncQueue.then(() => syncGameSurface(st)).finally(() => { embedSyncPending--; });
  embedSyncQueue = next.catch(() => {});
  return next;
});
async function syncEmbeddedGame(st) {
  // st: { pid, rect: {x,y,w,h} in window CSS px, visible }
  f3(!!(st && st.pid));
  if (!st || !st.pid) { if (embedded) { await embedCmd({ op: "hide" }); } return { ok: true }; }
  if (embedded !== st.pid) {
    const parent = Number(win.getNativeWindowHandle().readBigUInt64LE(0));
    const r = await embedCmd({ op: "attach", pid: st.pid, parent });
    if (!r.ok) return r;
    embedded = st.pid;
  }
  if (!st.visible) return embedCmd({ op: "hide" });
  const k = screen.getDisplayMatching(win.getBounds()).scaleFactor;
  return embedCmd(embedGeometry.nativePlacement(st.rect, st.holes || [], k, win.webContents.getZoomFactor() || 1));
}
// Update pending = app or worker code on disk changed after this app started (the logo click applies it).
const APP_START = Date.now();
ipcMain.handle("update:pending", async () => {
  // asynchronous (#712): the synchronous walk of ~320 files blocked the app's main thread ~25 ms every 20 s
  const root = settings().repoLocal;
  let newest = 0, file = "";
  const walk = async d => { for (const e of await fs.promises.readdir(d, { withFileTypes: true })) {
    if (["__pycache__", "node_modules", ".git"].includes(e.name)) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) await walk(p); else { const m = (await fs.promises.stat(p)).mtimeMs; if (m > newest) { newest = m; file = p; } } } };
  try { for (const d of ["clients/desktop", "gbox"]) { const p = path.join(root, d); if (fs.existsSync(p)) await walk(p); } } catch {}
  return { pending: newest > APP_START + 2000, changed: newest ? new Date(newest).toLocaleString() : "", file: file && path.relative(root, file) };
});
// AutoBrowse: gBox's browser (pages from search results / chat links, and the download queue)
const AUTOBROWSE = process.env.GBOX_AUTOBROWSE || "C:\\_tools\\AutoBrowse";
ipcMain.handle("browser:send", (_e, op, url) => {
  if (!/^https?:\/\//i.test(url || "")) return { ok: false, error: "http(s) only" };
  const exe = path.join(AUTOBROWSE, "system", "node_modules", "electron", "dist", "electron.exe");
  if (!fs.existsSync(exe)) { shell.openExternal(url); return { ok: false, fallback: "system browser", error: "AutoBrowse not installed" }; }
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
  spawn(exe, [path.join(AUTOBROWSE, "system"), `--${op === "download" ? "download" : "open"}=${url}`],
        { cwd: path.join(AUTOBROWSE, "system"), env, detached: true, stdio: "ignore" }).unref();
  return { ok: true };
});
// voice overlay: the visualizer floats over the docked game (a native window HTML can't draw on) while you and gBox talk.
// Click-through, never focused, parented to gBox so it moves/minimizes with it; partial opacity lets the game show through.
let vizOv = null;
ipcMain.handle("viz:overlay", (_e, st) => {
  if (!win || !st || !st.on || !st.rect) { if (vizOv && !vizOv.isDestroyed()) vizOv.hide(); return { on: false }; }
  const b = win.getContentBounds(), z = win.webContents.getZoomFactor() || 1, r = st.rect;
  const bounds = { x: Math.round(b.x + r.x * z), y: Math.round(b.y + r.y * z), width: Math.max(1, Math.round(r.w * z)), height: Math.max(1, Math.round(r.h * z)) };
  if (!vizOv || vizOv.isDestroyed()) {
    vizOv = new BrowserWindow({ parent: win, frame: false, show: false, focusable: false, skipTaskbar: true, resizable: false, movable: false,
                                hasShadow: false, backgroundColor: "#000000", webPreferences: { backgroundThrottling: false } });
    vizOv.setIgnoreMouseEvents(true);
    vizOv.loadURL(settings().apiUrl + "/viz/overlay.html" + (st.mode ? "?mode=" + encodeURIComponent(st.mode) : ""));
  }
  vizOv.setBounds(bounds); vizOv.setOpacity(Math.max(0.1, Math.min(0.9, st.opacity ?? 0.42)));
  // the app's menus and panels over the game stay above the visualizer, as they do above the game itself (#1081)
  try { vizOv.setShape(embedGeometry.shapeMinusHoles(bounds.width, bounds.height, st.holes || [], z)); } catch {}
  if (!vizOv.isVisible()) vizOv.showInactive();
  // a fresh conversation (#250) starts a new random transition visual; the level and beats follow who is talking
  if (st.level != null) vizOv.webContents.executeJavaScript(`window.gboxVoice && gboxVoice(${JSON.stringify({ level: +st.level || 0, beat: !!st.beat, ...(st.restart ? { mode: st.mode || "random" } : {}) })})`).catch(() => {});
  return { on: true };
});
ipcMain.handle("embed:kill", async () => { const r = embedded ? await embedCmd({ op: "kill" }) : { ok: false }; embedded = null; return r; });
ipcMain.handle("embed:focus", () => embedded ? embedCmd({ op: "focus" }) : { ok: false });
ipcMain.handle("app:focus", async () => { if (embedded) await embedCmd({ op: "unfocus" }); if (win) { win.focus(); win.webContents.focus(); } return { ok: true }; });
ipcMain.handle("embed:release", async () => { embedded = null; return embedCmd({ op: "detach" }); });

// speech: reply audio from the Pine Box Voice Director (XTTS v2 clones), Piper fallback
ipcMain.handle("tts", async (_e, text, voice) => {
  const r = await fetch(settings().apiUrl + "/api/tts", { method: "POST", body: JSON.stringify({ text, voice }),
    headers: { authorization: `Bearer ${await token()}`, "content-type": "application/json" }, signal: AbortSignal.timeout(150000) });
  if (!r.ok) throw new Error(await r.text());
  return new Uint8Array(await r.arrayBuffer());
});

// dictation: audio -> Spark /api/stt (faster-whisper over Wyoming)
ipcMain.handle("stt", async (_e, buf) => {
  const r = await fetch(settings().apiUrl + "/api/stt", { method: "POST", body: Buffer.from(buf),
    headers: { authorization: `Bearer ${await token()}`, "content-type": "audio/webm" }, signal: AbortSignal.timeout(60000) });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()).text;
});

// Mini mode: the whole app collapses into a frameless, always-on-top game window that keeps the game's aspect ratio.
let mini = null, miniSession = null, pendingMini = null;
async function openMini(sid, title, savedBounds) {
  const s = settings(), t = await token();
  if (clientHandoffBusy) throw Error('Desktop refresh is in progress.');
  if (mini) mini.close();
  mini = new BrowserWindow({ width: 480, height: 360, frame: false, alwaysOnTop: true, resizable: true, backgroundColor: "#000",
    title: "gBox · " + (title || "game"), icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true } });
  mini.loadFile(path.join(__dirname, "mini.html"), { query: { src: `${s.apiUrl}/api/sessions/${encodeURIComponent(sid)}/mjpeg?token=${encodeURIComponent(t)}`, title: title || "" } });
  miniSession = { sid, title };
  if (savedBounds) mini.setBounds(savedBounds);
  mini.on("closed", () => { mini = null; miniSession = null; queueClientView(); if (win && !win.isDestroyed()) { win.webContents.send("mini:closed"); win.show(); } });
  mini.on('move', queueClientView); mini.on('resize', queueClientView); queueClientView();
  win.hide();
  return true;
}
ipcMain.handle("mini:open", (_e, sid, title) => openMini(sid, title));
ipcMain.handle("mini:aspect", (_e, w, h) => { if (mini && w && h) { mini.setAspectRatio(w / h); const [cw] = mini.getSize(); mini.setSize(cw, Math.round(cw * h / w)); } });
ipcMain.handle("mini:restore", () => { if (mini) mini.close(); });

// Screenshot of the whole app window (including the embedded gBox view) as a PNG data URL.
ipcMain.handle("capture", async () => {
  if (embedded) { const os = await osShot(); if (os) return os; }   // a docked GPU game: only the screen has its pixels
  const img = await win.webContents.capturePage();
  if (!img.isEmpty()) return img.toDataURL();
  const { width, height } = win.getContentBounds();             // fallback: OS-level capture of this window
  const srcs = await desktopCapturer.getSources({ types: ["window"], thumbnailSize: { width, height } });
  const me = srcs.find(s => s.id === win.getMediaSourceId()) || srcs.find(s => s.name === win.getTitle());
  return me ? me.thumbnail.toDataURL() : null;
});

// OS-level capture of this window: includes the docked native game window (capturePage only sees the web content).
const osShot = async () => {
  // grab the SCREEN gBox is on and crop to the window's content: window capture returns the docked GPU game window black
  const d = screen.getDisplayMatching(win.getBounds()), c = win.getContentBounds(), k = d.scaleFactor;
  try {
    const srcs = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: Math.round(d.bounds.width * k), height: Math.round(d.bounds.height * k) } });
    const sc = srcs.find(x => x.display_id === String(d.id)) || srcs[0];
    if (sc && !sc.thumbnail.isEmpty()) {
      const r = { x: Math.round((c.x - d.bounds.x) * k), y: Math.round((c.y - d.bounds.y) * k), width: Math.round(c.width * k), height: Math.round(c.height * k) };
      return sc.thumbnail.crop(r).toDataURL();
    }
  } catch {}
  const srcs = await desktopCapturer.getSources({ types: ["window"], thumbnailSize: { width: Math.round(c.width * k), height: Math.round(c.height * k) } });
  const me = srcs.find(s => s.id === win.getMediaSourceId()) || srcs.find(s => s.name === win.getTitle());
  return me ? me.thumbnail.toDataURL() : null;
};
ipcMain.handle("capture:os", osShot);

// Update & relaunch (logo click): pull latest code here and on the Spark, rebuild/reinitialize the Spark
// (bootstrap: deps, setup, service restart), stop this PC's worker, then relaunch the app (worker restarts on launch).
ipcMain.handle("app:relaunch", async () => {
  if (clientHandoffBusy) throw Error('Desktop refresh is already in progress.');
  const s = settings();
  const log = t => send("task", "relaunch", t);
  if (fs.existsSync(path.join(s.repoLocal, ".git"))) {
    log("$ git pull (this PC)\n");
    await stream("relaunch-git", "git", ["-C", s.repoLocal, "pull", "--ff-only"]);
  }
  log("$ spark: update + rebuild + restart\n");
  const probe = await ssh("true", 8000);
  if (probe.ok) {
    await stream("relaunch-spark", "ssh", ["-o", "BatchMode=yes", s.sshHost,
      `cd ${s.repoRemote} && (if [ -d .git ]; then git pull --ff-only; fi) && sed -i 's/\\r$//' scripts/bootstrap-linux.sh && bash scripts/bootstrap-linux.sh`]);
  } else {
    log("! no SSH to the Spark from this PC: skipped the Spark rebuild (the app still relaunches)\n");
  }
  log("keeping the moment of this PC's running games (Reload with your last moment)…\n");
  await keepMoments();                                          // before the worker (and its games) go
  if (worker) { workerStopRequested = true; execFile("taskkill", ["/T", "/F", "/PID", String(worker.pid)]); worker = null; }
  log("relaunching…\n");
  setTimeout(() => { shutdownSessions(); app.relaunch(); app.exit(0); }, 800);
  return true;
});

// ---------------- File > Decant… (gbox/decant.py): a zip someone else installs as a standalone gBox ----------------
// The manifest (what goes in, what is left out and why) is shown before saving. Code from the canonical tree when it's
// reachable (the Spark share), else this PC's checkout; recipes from the control plane; nothing from anyone's games.
function decantArgs(extra) {
  const s = settings();
  const src = fs.existsSync(path.join(s.repoShare || "", "gbox", "decant.py")) ? s.repoShare : s.repoLocal;
  const a = ["-P", "-m", "gbox.decant", ...extra, "--server", s.apiUrl, "--src", src];
  if (s.sshHost && s.repoRemote) a.push("--cheatdb-ssh", `${s.sshHost}:${s.repoRemote}/gbox-data/cheatdb`);
  else a.push("--cheatdb-dir", path.join(src, "gbox-data", "cheatdb"));
  return a;
}
function decantRun(extra) {
  return new Promise(async resolve => {
    const t = await token();
    if (clientHandoffBusy) return resolve({ error: 'Desktop refresh is in progress.' });
    if (!t) return resolve({ error: "no API token (Settings)" });
    if (!fs.existsSync(venvPython())) return resolve({ error: "gBox's Python environment isn't installed on this PC" });
    const p = spawn(venvPython(), decantArgs(extra), { env: { ...process.env, PYTHONPATH: settings().repoLocal, GBOX_TOKEN: t, PYTHONUNBUFFERED: "1" },
                                                       cwd: os.homedir(), windowsHide: true });
    procs.set("decant", p);
    taskLogs.set("decant", { id: "decant", pid: p.pid, started: Date.now() / 1000, state: "running", output: "" });
    try { os.setPriority(p.pid, os.constants.priority.PRIORITY_BELOW_NORMAL); } catch {}   // never slow down a game being played
    let out = "", err = "";
    p.stdout.on("data", d => { out += d; });
    p.stderr.on("data", d => { err += d; for (const l of String(d).split(/\r?\n/)) { if (!l.trim()) continue;
      try { const o = JSON.parse(l); send("decant", o.log || l); send("task", "decant", (o.log || l) + "\n"); }
      catch { send("decant", l); send("task", "decant", l + "\n"); } } });
    p.on("close", code => { procs.delete("decant"); taskDone("decant", code);
      try { resolve(JSON.parse(out.trim().split(/\r?\n/).pop())); }
      catch { resolve({ error: `decant exited ${code}: ${(err || out).trim().split(/\r?\n/).slice(-4).join(" ")}` }); } });
  });
}
ipcMain.handle("decant:plan", () => decantRun(["plan"]));
ipcMain.handle("decant:save", async () => {
  const name = `gBox-decant-${new Date().toISOString().slice(0, 10)}.zip`;
  const r = await dialog.showSaveDialog(win, { title: "Save the decanted gBox", defaultPath: path.join(app.getPath("downloads"), name),
                                               filters: [{ name: "Zip", extensions: ["zip"] }] });
  if (r.canceled || !r.filePath) return null;
  return decantRun(["pack", "--out", r.filePath]);
});
ipcMain.handle("decant:cancel", () => { const p = procs.get("decant"); if (p) p.kill(); return !!p; });
ipcMain.handle("decant:show", (_e, file) => shell.showItemInFolder(file));

function appMenu() {                                  // the menu bar is hidden (custom title bar) but its accelerators work
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "File", submenu: [
      { label: "Decant…", accelerator: "CmdOrCtrl+Shift+D", click: () => send("menu", "decant") },
      { type: "separator" }, { role: "quit" } ] },
    { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" },
  ]));
}

// ---------------- window ----------------
app.setAppUserModelId("com.gbox.desktop");                 // taskbar groups under the gBox icon
app.setName("gBox");                                        // name in menus / about / notifications
// one gBox: opening it again (taskbar pin, shortcut) focuses the running window instead of starting a second app + worker
const FIRST = app.requestSingleInstanceLock();
if (!FIRST) app.quit();
app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); } });
app.whenReady().then(() => {
  clientVersions = require('./client-version.cjs').create({ desktop: __dirname, web: path.join(__dirname, '../web'),
    runtimeFiles: [...new Set([path.join(__dirname, 'main.js'), ...Object.keys(require.cache).filter(p => p.startsWith(__dirname + path.sep))])], apiUrl: () => settings().apiUrl });
  if (!FIRST) return;
  startupHandoff = clientHandoff.consume(CLIENT_HANDOFF_FILE, process.argv);
  // A cold reopen restores presentation only. It cannot enter the handoff's
  // cleanup exception or authorize a worker start.
  const startupView = startupHandoff.value || (!startupHandoff.requested && clientViewStore.load(settings().apiUrl));
  if (startupView) {
    savedClientState = startupView.state; savedClientOrigin = clientViews.origin(settings().apiUrl);
    pendingMini = startupView.mini;
    compactWindow.seedBounds(startupView.compactBounds);
  }
  if (startupHandoff.value) {
    handoffView = startupHandoff.value.state;
    pendingMini = startupHandoff.value.mini;
    compactWindow.seedBounds(startupHandoff.value.compactBounds);
    clientActivation = { state: 'applied', pid: process.pid, at: Date.now(), reason: 'Updated desktop code is active; saved streams are reconnecting.' };
  } else if (startupHandoff.requested) clientActivation = { state: 'pending', pid: process.pid, reason: startupHandoff.error };
  appMenu();
  session.defaultSession.setPermissionRequestHandler((_wc, perm, cb) => cb(["media", "audioCapture", "clipboard-read", "clipboard-sanitized-write"].includes(perm)));
  session.defaultSession.setPermissionCheckHandler((_wc, perm) => ["media", "audioCapture"].includes(perm));
  // <display-media-handler>
  // Electron's display-media callback is one-time. The old handler answered again from its catch when the first
  // answer threw, so the real refusal was replaced by "One-time callback was called more than once" (an unhandled
  // rejection) and the recording aborted (#1118). Answer exactly once, log the first refusal, and offer loopback
  // audio only when the request asked for audio.
  function displayMediaHandler(getRec, getWin, capturer, log = (...a) => console.warn(...a)) {
    return async (request, callback) => {
      let answered = false;
      const answer = streams => {
        if (answered) return false;
        answered = true;
        try { callback(streams); return true; }
        catch (error) { log("[recording] screen capture answer refused:", error?.message || String(error)); return false; }
      };
      // Loopback captures the PC's playback audio, including native and streamed games; never the microphone.
      if (!getRec() || request.frame !== getWin()?.webContents.mainFrame) return answer({});
      let source = null;
      try {
        const sources = await capturer.getSources({ types: ["screen"], thumbnailSize: { width: 0, height: 0 } });
        source = sources.find(s => s.display_id === String(getRec()?.display.id)) || null;
      } catch (error) {
        log("[recording] screen sources unavailable:", error?.message || String(error));
      }
      if (!source || !getRec()) return answer({});
      return answer(request.audioRequested === false ? { video: source } : { video: source, audio: "loopback" });
    };
  }
  // </display-media-handler>
  session.defaultSession.setDisplayMediaRequestHandler(displayMediaHandler(() => rec, () => win, desktopCapturer));
  win = new BrowserWindow({
    width: 1500, height: 950, title: "gBox", backgroundColor: "#16161a", autoHideMenuBar: true,
    icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    titleBarStyle: "hidden",                                         // custom title bar (capture + eyedropper icons)
    titleBarOverlay: { color: "#111114", symbolColor: "#e8e8ee", height: 36 },
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, webviewTag: true, backgroundThrottling: false },
  });
  if (startupView) {
    const before = startupView.window;
    win.setBounds(before.bounds); win.setAlwaysOnTop(before.top);
    if (before.maximized) win.maximize();
    if (before.fullscreen) win.setFullScreen(true);
  }
  if (process.platform === "win32")                          // pinning the window pins *this* command (exe + app folder), same taskbar slot
    win.setAppDetails({ appId: "com.gbox.desktop", relaunchDisplayName: "gBox", appIconPath: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
                        relaunchCommand: `"${process.execPath}" "${app.getAppPath()}"` });
  win.loadFile(path.join(__dirname, "index.html"));
  backgroundPower = require('./background-power').create({powerSaveBlocker,
    status:()=>api('/api/background/workers/'+encodeURIComponent(settings().workerName)+'/status')});
  backgroundPower.start();
  win.webContents.on("did-start-navigation", (_e, _url, inPlace, mainFrame) => { if (mainFrame && !inPlace) {
    pickHoldReleaseAll("window reloaded");
    if (!clientReloading && compactWindow.state().on) compactWindow.restore().catch(error => logPush('compact', error.message));
  } });
  win.webContents.on('did-finish-load', () => {
    clientReloading = false;
    if (pendingMini) {
      const target = pendingMini;
      api('/api/sessions?include_ended=false').then(sessions => {
        if (!sessions.some(value => value.session_id === target.sid && value.state === 'running')) throw Error('The saved PiP session is unavailable.');
        return openMini(target.sid, target.title, target.bounds);
      }).then(() => { if (pendingMini === target) pendingMini = null; }).catch(error => {
        clientActivation = { ...clientActivation, reason: error.message + ' Press F5 to retry the saved PiP.' };
      });
    }
  });
  win.webContents.on('did-fail-load', (_e, _code, _description, _url, mainFrame) => { if (mainFrame) clientReloading = false; });
  win.webContents.on('render-process-gone', () => { clientReloading = false; });
  win.on("closed", () => pickHoldReleaseAll("window closed"));
  for (const event of ['move', 'resize', 'maximize', 'unmaximize', 'enter-full-screen', 'leave-full-screen']) win.on(event, queueClientView);
  startPadWatcher();
  win.on("focus", () => { win.webContents.send("app-focus"); if (hotkeys.docked) checkFront(); });   // coming back to gBox: the renderer decides whether the game gets focus
  // Another app took the foreground / gBox minimized: release the game hotkeys at once, then confirm with the helper (a
  // blur can also mean the docked game took the keyboard inside gBox, which keeps them).
  win.on("blur", () => { hotkeys.setFront(false); if (hotkeys.docked) checkFront(); });
  win.on("minimize", () => hotkeys.setFront(false));
  win.on("hide", () => hotkeys.setFront(false));
  win.on("restore", () => { if (hotkeys.docked) checkFront(); });
  win.on("close", e => {                                      // the docked game dies with this window: keep its moment first
    try { saveClientView(); } catch (error) { logPush('saved-view', error.message); }
    if (momentsKept || !FIRST) return;
    e.preventDefault();
    keepMoments().finally(() => { if (win && !win.isDestroyed()) win.close(); });
  });
  if (startupHandoff.requested) {
    // The old parent already waited for an idle worker to exit. Never sweep
    // other processes or bootstrap Spark while restoring a desktop handoff.
    if (startupHandoff.value?.startWorker) startWorker();
  } else cleanupSessions(false).then(out => {                        // leftovers from a previous run, before this run's worker starts
    if (out.trim()) send("task", "win-worker", "closed leftover gBox processes:\n" + out);
    if (settings().autoStartWorker) startWorker();
  });
  startAudioVolumeHelper();
});
let sessionsShutDown = false;
function shutdownSessions() {
  backgroundPower?.dispose();
  pickHoldReleaseAll("gBox quitting");
  if (sessionsShutDown) return;
  sessionsShutDown = true;
  quitting = true;
  audioVolumeHelper?.kill();
  app.isQuitting = true;
  if (padWatcher) { padWatcher.kill(); padWatcher = null; }
  if (!FIRST) return;
  if (clientRefreshExit) {
    // Only idle, parent-owned helpers remain. No game/job cleanup or Spark action.
    embedder?.kill();
    return;
  }
  try { embedder && embedder.stdin.write(JSON.stringify({ op: "detach" }) + "\n"); } catch {}
  for (const p of procs.values()) p.kill();
  workerStopRequested = true;
  if (worker) { try { execFileSync("taskkill", ["/T", "/F", "/PID", String(worker.pid)], { windowsHide: true, timeout: 8000 }); } catch {} }
  cleanupSessions(true);                                       // every game this PC was running for gBox closes with it
}
app.on("window-all-closed", () => {
  shutdownSessions();
  app.quit();
});
