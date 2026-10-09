// gBox desktop manager (Electron main process).
// Manages: the Spark control plane (over SSH: install/update, start/stop, logs), the local Windows worker,
// dependency setup on both nodes, and hosts the gBox web UI with the API token injected.
const { app, BrowserWindow, ipcMain, shell, desktopCapturer, session, screen, dialog, clipboard, nativeImage, globalShortcut, Menu } = require("electron");
const { spawn, execFile, execFileSync } = require("child_process");

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

app.setPath("userData", STANDALONE ? path.join(STANDALONE, ".tools", "desktop-profile")       // standalone: own profile + single-instance lock
                                  : path.join(app.getPath("appData"), "gbox-desktop"));   // keep settings where they were (productName = gBox)
const SETTINGS = path.join(app.getPath("userData"), "settings.json");
const DEFAULTS = {
  sshHost: "spark",                                   // ~/.ssh/config alias (key auth, BatchMode); optional
  apiUrl: "http://10.89.1.246:8765",
  repoRemote: "~/gBox/system",                        // gBox system folder on the Spark
  repoLocal: path.resolve(__dirname, "..", ".."),     // this PC's checkout (share or GitHub clone): runs the worker
  repoShare: "\\\\10.89.1.246\\ehm_eckx\\gBox\\system",  // optional: the Spark's system folder over SMB (token lookup)
  token: "",                                          // optional: paste once if neither share nor SSH is reachable
  workerName: os.hostname(),
  autoStartWorker: true,
};
if (STANDALONE) Object.assign(DEFAULTS, { sshHost: "", apiUrl: process.env.GBOX_API_URL || "http://127.0.0.1:8765",
  repoLocal: path.join(STANDALONE, "system"), repoShare: path.join(STANDALONE, "system"), repoRemote: "" });
const settings = () => {
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

let win, worker = null, workerStopRequested = false;
const procs = new Map();                              // id -> child process (streamed tasks)
const taskLogs = new Map();                           // recent app commands and their streamed output
// console output of the whole app (main process, renderer + gBox webview, worker / task streams) for issue reports
let CONSOLE = "";
const logPush = (src, text) => { CONSOLE = (CONSOLE + `${new Date().toISOString().slice(11, 23)} [${src}] ${String(text).replace(/\n+$/, "")}\n`).slice(-400000); };
for (const lv of ["log", "warn", "error"]) { const orig = console[lv].bind(console); console[lv] = (...a) => { logPush("main:" + lv, a.map(String).join(" ")); orig(...a); }; }
app.on("web-contents-created", (_e, wc) => wc.on("console-message", (ev, level, message, line, source) => {
  const m = ev?.message ?? message, lv = ev?.level ?? level, src = ev?.sourceId ?? source, ln = ev?.lineNumber ?? line;
  logPush(`${wc.getType()}:${lv}`, `${m}${src ? `  (${String(src).split("/").pop()}:${ln})` : ""}`);
}));
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

async function api(p, body) {
  const t = await token();
  const r = await fetch(settings().apiUrl + p, {
    method: body ? "POST" : "GET", body: body && JSON.stringify(body),
    headers: { authorization: `Bearer ${t}`, "content-type": "application/json" },
    signal: AbortSignal.timeout(p === "/api/tasks" ? 35000 : 8000),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

// ---------------- IPC ----------------
ipcMain.handle("settings:get", () => settings());
ipcMain.handle("settings:save", (_e, s) => { fs.mkdirSync(path.dirname(SETTINGS), { recursive: true }); fs.writeFileSync(SETTINGS, JSON.stringify({ ...settings(), ...s }, null, 1)); cachedToken = null; return settings(); });
ipcMain.handle("token", () => token());
ipcMain.handle("settings:reset-token", () => { cachedToken = null; return true; });
ipcMain.handle("api", async (_e, p, body) => { try { return { ok: true, data: await api(p, body) }; } catch (e) { return { ok: false, error: e.message }; } });

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

async function startWorker() {
  const s = settings();
  if (worker) return { running: true };
  if (!fs.existsSync(venvPython())) return { running: false, error: "Windows node not installed yet — run 'Install / update Windows node'" };
  if (STANDALONE) {                                   // this PC is the whole gBox: control plane + worker in one process
    const cfg = path.join(s.repoLocal, "gbox.toml");
    worker = spawn(venvPython(), ["-P", "-m", "gbox", "--config", cfg, "serve", "--worker"],
      { env: { ...process.env, PYTHONPATH: s.repoLocal, GBOX_CONFIG: cfg, PYTHONUNBUFFERED: "1" }, cwd: s.repoLocal, windowsHide: true });
  } else {
    const t = await token();
    if (!t) return { running: false, error: "no API token: paste it in Settings, or make the Spark share / SSH reachable" };
    worker = spawn(venvPython(), ["-P", "-m", "gbox", "--config", path.join(s.repoLocal, "gbox.toml"), "worker", "--server", s.apiUrl, "--name", s.workerName],
      { env: { ...process.env, PYTHONPATH: s.repoLocal, GBOX_TOKEN: t, PYTHONUNBUFFERED: "1" }, cwd: os.homedir(), windowsHide: true });
  }
  const out = d => send("task", "win-worker", d.toString());
  worker.stdout.on("data", out); worker.stderr.on("data", out);
  worker.on("close", code => {
    send("task", "win-worker", `\n[worker exited ${code}]\n`); worker = null; send("worker", false);
    if (!workerStopRequested && settings().autoStartWorker) setTimeout(startWorker, 5000);   // watchdog
    workerStopRequested = false;
  });
  send("worker", true);
  return { running: true };
}
ipcMain.handle("win:worker", (_e, op) => {
  if (op === "start") return startWorker();
  if (op === "stop" && worker) { workerStopRequested = true; execFile("taskkill", ["/T", "/F", "/PID", String(worker.pid)]); return { running: false }; }
  return { running: !!worker };
});

ipcMain.handle("open:external", (_e, url) => shell.openExternal(url));

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
  const p = spawn(exe, args, { windowsHide: true }); let err = "";
  procs.set("rec-fit", p);
  taskLogs.set("rec-fit", { id: "rec-fit", pid: p.pid, started: Date.now() / 1000, state: "running", output: "" });
  p.stderr.on("data", d => { err = (err + d).slice(-2000); send("task", "rec-fit", String(d)); });
  p.stdout.on("data", d => send("task", "rec-fit", String(d)));
  p.on("error", e => { err = e.message; send("task", "rec-fit", `[error] ${e.message}\n`); });
  p.on("close", code => { procs.delete("rec-fit"); taskDone("rec-fit", code);
    code === 0 ? res() : rej(new Error(`${path.basename(exe)} exit ${code}: ${err.split("\n").slice(-3).join(" ")}`)); });
});
ipcMain.handle("rec:fit", async (_e, file, o) => {
  const target = (o.targetMB || 10) * 1048576, size = fs.statSync(file).size;
  if (size <= target) return { file, bytes: size, compressed: false };
  const dur = Math.max(1, o.seconds || 1), preset = { fast: "veryfast", balanced: "medium", best: "slow" }[o.speed] || "medium";
  const hb = findExe("HandBrakeCLI.exe"), ff = findExe("ffmpeg.exe");
  if (!hb && !ff) throw new Error("neither HandBrakeCLI nor ffmpeg is installed (winget install HandBrake.HandBrake.CLI)");
  const audioKbps = 128;
  let kbps = Math.max(120, Math.floor(target * 8 * 0.92 / 1000 / dur) - audioKbps);
  for (let attempt = 0; attempt < 3; attempt++) {
    const h = kbps >= 3500 ? 1080 : kbps >= 1800 ? 720 : kbps >= 900 ? 540 : kbps >= 450 ? 360 : 240, fps = kbps < 900 ? 30 : 60;
    const out = file.replace(/\.(mp4|webm)$/i, "") + `-${o.targetMB}MB.mp4`;
    send("task", "rec", `compressing ${path.basename(file)} to ≤${o.targetMB} MB: ${kbps} kbps, ${h}p, ${fps} fps (${hb ? "HandBrake" : "ffmpeg"})\n`);
    if (hb) await runExe(hb, ["-i", file, "-o", out, "-e", "x264", "--encoder-preset", preset, "-b", String(kbps), "--multi-pass", "--turbo",
                              "--maxHeight", String(h), "-r", String(fps), "--pfr", "-a", "1", "-E", "av_aac", "-B", String(audioKbps), "-O"]);
    else await runExe(ff, ["-y", "-i", file, "-map", "0:v:0", "-map", "0:a:0?", "-c:a", "aac", "-b:a", `${audioKbps}k`, "-vf", `scale=-2:'min(${h},ih)'`, "-r", String(fps), "-c:v", "libx264", "-preset", preset,
                           "-b:v", `${kbps}k`, "-maxrate", `${kbps}k`, "-bufsize", `${kbps * 2}k`, "-movflags", "+faststart", out]);
    const got = fs.statSync(out).size;
    if (got <= target) {
      let final = out;
      if (!o.keep) { fs.unlinkSync(file); final = file.replace(/\.webm$/i, ".mp4"); fs.renameSync(out, final); }
      return { file: final, bytes: got, compressed: true, original: size, kbps, height: h, tool: hb ? "HandBrake" : "ffmpeg" };
    }
    fs.unlinkSync(out); kbps = Math.max(80, Math.floor(kbps * target / got * 0.9));   // overshot: aim lower and retry
  }
  throw new Error(`couldn't get ${path.basename(file)} under ${o.targetMB} MB`);
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
  if (input.key === "Escape" && win.isFullScreen()) { win.setFullScreen(false); win.webContents.send("fullscreen", false); ev.preventDefault(); }
  else if (toggle) { win.webContents.send("hotkey", "fullscreen"); ev.preventDefault(); }   // the page's view mode follows
  else if (input.key === "F2" && (input.shift || input.control) && !input.alt) { win.webContents.send("hotkey", input.shift ? "slot+" : "slot-"); ev.preventDefault(); }
  else if (GAME_KEYS[input.key] && !input.control && !input.alt && !input.shift) { win.webContents.send("hotkey", GAME_KEYS[input.key]); ev.preventDefault(); }
}));
// Universal game hotkeys, the same for every emulator: F2 save state, F4 load state, F3 autoplay on/off.
// Inside gBox (any page, the streamed view included) they arrive here; while a native game window has the keyboard they come
// through global shortcuts (registered only while a game is docked, see f3()).
const GAME_KEYS = { F2: "save", F3: "autoplay", F4: "load", F5: "reset" };   // F5 = the console's reset switch
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
      if (m.event) { if (win) { const k = screen.getDisplayMatching(win.getBounds()).scaleFactor; win.webContents.send("embed:event", { ...m, x: m.x / k, y: m.y / k }); } continue; }
      const r = embedQ.shift(); r && r(m); } });
    embedder.on("close", () => { embedder = null; embedded = null; embedQ.splice(0).forEach(r => r({ ok: false })); });
  }
  return new Promise(res => { embedQ.push(res); embedder.stdin.write(JSON.stringify(cmd) + "\n"); });
}
let embedded = null;                                             // pid currently inside the app
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
// ponytail: F3 is taken system-wide only while a game is docked in gBox; scope it to foreground if that ever bites.
function f3(on) {
  // F2 save · Shift/Ctrl+F2 slot ± · F4 load · Alt+Enter / F11 = full screen on/off (the docked game owns the keyboard, so
  // without these there is no way out of full screen from inside the game; Esc stays the game's own key)
  const keys = { ...GAME_KEYS, "Shift+F2": "slot+", "CommandOrControl+F2": "slot-", "CommandOrControl+I": "eyedropper",
                 "Alt+Enter": "fullscreen", "F11": "fullscreen" };
  try { if (on && !globalShortcut.isRegistered("F3")) Object.entries(keys).forEach(([k, a]) => globalShortcut.register(k, () => win && win.webContents.send("hotkey", a)));
        else if (!on && globalShortcut.isRegistered("F3")) Object.keys(keys).forEach(k => globalShortcut.unregister(k)); } catch {}
}
let embedSyncQueue = Promise.resolve();
ipcMain.handle("embed:sync", (_e, st) => {
  const next = embedSyncQueue.then(() => syncEmbeddedGame(st));
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
  return embedCmd({ op: "move", x: Math.round(st.rect.x * k), y: Math.round(st.rect.y * k), w: Math.round(st.rect.w * k), h: Math.round(st.rect.h * k),
                    holes: (st.holes || []).map(h => [h.x, h.y, h.w, h.h].map(v => Math.round(v * k))) });
}
// Update pending = app or worker code on disk changed after this app started (the logo click applies it).
const APP_START = Date.now();
ipcMain.handle("update:pending", () => {
  const root = settings().repoLocal;
  let newest = 0, file = "";
  const walk = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    if (["__pycache__", "node_modules", ".git"].includes(e.name)) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p); else { const m = fs.statSync(p).mtimeMs; if (m > newest) { newest = m; file = p; } } } };
  try { ["clients/desktop", "gbox"].forEach(d => { const p = path.join(root, d); if (fs.existsSync(p)) walk(p); }); } catch {}
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
  if (!vizOv.isVisible()) vizOv.showInactive();
  if (st.level != null) vizOv.webContents.executeJavaScript(`window.gboxVoice && gboxVoice(${JSON.stringify({ level: +st.level || 0, beat: !!st.beat })})`).catch(() => {});
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
let mini = null;
ipcMain.handle("mini:open", async (_e, sid, title) => {
  const s = settings(), t = await token();
  if (mini) mini.close();
  mini = new BrowserWindow({ width: 480, height: 360, frame: false, alwaysOnTop: true, resizable: true, backgroundColor: "#000",
    title: "gBox · " + (title || "game"), icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true } });
  mini.loadFile(path.join(__dirname, "mini.html"), { query: { src: `${s.apiUrl}/api/sessions/${encodeURIComponent(sid)}/mjpeg?token=${encodeURIComponent(t)}`, title: title || "" } });
  mini.on("closed", () => { mini = null; if (win && !win.isDestroyed()) win.show(); });
  win.hide();
  return true;
});
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
  if (worker) { workerStopRequested = true; execFile("taskkill", ["/T", "/F", "/PID", String(worker.pid)]); worker = null; }
  log("relaunching…\n");
  setTimeout(() => { app.relaunch(); app.exit(0); }, 800);
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
  if (!FIRST) return;
  appMenu();
  session.defaultSession.setPermissionRequestHandler((_wc, perm, cb) => cb(["media", "audioCapture", "clipboard-read", "clipboard-sanitized-write"].includes(perm)));
  session.defaultSession.setPermissionCheckHandler((_wc, perm) => ["media", "audioCapture"].includes(perm));
  session.defaultSession.setDisplayMediaRequestHandler(async (request, callback) => {
    // Loopback captures the PC's playback audio, including native and streamed games; never the microphone.
    if (!rec || request.frame !== win?.webContents.mainFrame) return callback({});
    try {
      const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 0, height: 0 } });
      const source = sources.find(s => s.display_id === String(rec?.display.id));
      callback(source ? { video: source, audio: "loopback" } : {});
    } catch { callback({}); }
  });
  win = new BrowserWindow({
    width: 1500, height: 950, title: "gBox", backgroundColor: "#16161a", autoHideMenuBar: true,
    icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    titleBarStyle: "hidden",                                         // custom title bar (capture + eyedropper icons)
    titleBarOverlay: { color: "#111114", symbolColor: "#e8e8ee", height: 36 },
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, webviewTag: true },
  });
  if (process.platform === "win32")                          // pinning the window pins *this* command (exe + app folder), same taskbar slot
    win.setAppDetails({ appId: "com.gbox.desktop", relaunchDisplayName: "gBox", appIconPath: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
                        relaunchCommand: `"${process.execPath}" "${app.getAppPath()}"` });
  win.loadFile(path.join(__dirname, "index.html"));
  win.on("focus", () => win.webContents.send("app-focus"));   // coming back to gBox: the renderer decides whether the game gets focus
  cleanupSessions(false).then(out => {                        // leftovers from a previous run, before this run's worker starts
    if (out.trim()) send("task", "win-worker", "closed leftover gBox processes:\n" + out);
    if (settings().autoStartWorker) startWorker();
  });
});
app.on("window-all-closed", () => {
  if (!FIRST) return app.quit();
  try { embedder && embedder.stdin.write(JSON.stringify({ op: "detach" }) + "\n"); } catch {}
  for (const p of procs.values()) p.kill();
  workerStopRequested = true;
  if (worker) { try { execFileSync("taskkill", ["/T", "/F", "/PID", String(worker.pid)], { windowsHide: true, timeout: 8000 }); } catch {} }
  cleanupSessions(true);                                       // every game this PC was running for gBox closes with it
  app.quit();
});
