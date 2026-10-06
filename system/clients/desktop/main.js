// G-Box desktop manager (Electron main process).
// Manages: the Spark control plane (over SSH: install/update, start/stop, logs), the local Windows worker,
// dependency setup on both nodes, and hosts the G-Box web UI with the API token injected.
const { app, BrowserWindow, ipcMain, shell, desktopCapturer, session, screen } = require("electron");
const { spawn, execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

app.setPath("userData", path.join(app.getPath("appData"), "gbox-desktop"));   // keep settings where they were (productName = G-Box)
const SETTINGS = path.join(app.getPath("userData"), "settings.json");
const DEFAULTS = {
  sshHost: "spark",                                   // ~/.ssh/config alias (key auth, BatchMode); optional
  apiUrl: "http://10.89.1.246:8765",
  repoRemote: "~/gBox/system",                        // G-Box system folder on the Spark
  repoLocal: path.resolve(__dirname, "..", ".."),     // this PC's checkout (share or GitHub clone): runs the worker
  repoShare: "\\\\10.89.1.246\\ehm_eckx\\gBox\\system",  // optional: the Spark's system folder over SMB (token lookup)
  token: "",                                          // optional: paste once if neither share nor SSH is reachable
  workerName: os.hostname(),
  autoStartWorker: true,
};
const settings = () => {
  const s = { ...DEFAULTS, ...(fs.existsSync(SETTINGS) ? JSON.parse(fs.readFileSync(SETTINGS, "utf8")) : {}) };
  // layout migration: everything moved under <root>/system (root = gBox.exe + system/)
  if (/[\\/]gBox$/i.test(s.repoShare || "")) s.repoShare += "\\system";
  if ((s.repoRemote || "").replace(/\/$/, "") === "~/gBox") s.repoRemote = "~/gBox/system";
  if (!fs.existsSync(path.join(s.repoLocal || "", "gbox.toml"))) s.repoLocal = DEFAULTS.repoLocal;
  return s;
};
// The G-Box UI is served over plain HTTP on the LAN; Chromium only exposes the microphone (dictation, Talk)
// to secure origins, so mark the configured Spark origin as trusted. Must run before the app is ready.
try { app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", new URL(settings().apiUrl).origin); } catch {}
const venvPython = () => path.join(process.env.LOCALAPPDATA, "gbox", "venv", "Scripts", "python.exe");

let win, worker = null, workerStopRequested = false;
const procs = new Map();                              // id -> child process (streamed tasks)
const send = (ch, ...a) => win && !win.isDestroyed() && win.webContents.send(ch, ...a);

function stream(id, cmd, args, opts = {}) {
  // Run a command, streaming stdout/stderr lines to the renderer as `task:<id>` events.
  return new Promise(resolve => {
    const p = spawn(cmd, args, { windowsHide: true, ...opts });
    procs.set(id, p);
    const out = d => send("task", id, d.toString());
    p.stdout.on("data", out); p.stderr.on("data", out);
    p.on("error", e => { send("task", id, `\n[error] ${e.message}\n`); });
    p.on("close", code => { procs.delete(id); send("task-end", id, code); resolve(code); });
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
    headers: { authorization: `Bearer ${t}`, "content-type": "application/json" }, signal: AbortSignal.timeout(8000),
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

ipcMain.handle("task:cancel", (_e, id) => { const p = procs.get(id); if (p) p.kill(); return !!p; });

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
  const t = await token();
  if (!t) return { running: false, error: "no API token: paste it in Settings, or make the Spark share / SSH reachable" };
  worker = spawn(venvPython(), ["-P", "-m", "gbox", "--config", path.join(s.repoLocal, "gbox.toml"), "worker", "--server", s.apiUrl, "--name", s.workerName],
    { env: { ...process.env, PYTHONPATH: s.repoLocal, GBOX_TOKEN: t, PYTHONUNBUFFERED: "1" }, cwd: os.homedir(), windowsHide: true });
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

// Screen recording: the renderer records this window (MediaRecorder, H.264 MP4) and streams 1 s chunks here,
// appended straight to disk so long sessions never sit in memory.
const REC_DIR = path.join(process.env.LOCALAPPDATA || app.getPath("videos"), "gbox", "recordings");
let rec = null;
ipcMain.handle("rec:start", (_e, ext) => {
  fs.mkdirSync(REC_DIR, { recursive: true });
  const file = path.join(REC_DIR, `gbox-${new Date().toISOString().replace(/[:.]/g, "-")}.${ext}`);
  rec = { file, out: fs.createWriteStream(file), bytes: 0 };
  return { sourceId: win.getMediaSourceId(), file };
});
ipcMain.handle("rec:chunk", (_e, buf) => { if (rec) { rec.out.write(Buffer.from(buf)); rec.bytes += buf.byteLength; } return rec ? rec.bytes : 0; });
ipcMain.handle("rec:stop", () => new Promise(res => {
  if (!rec) return res(null);
  const r = rec; rec = null;
  r.out.end(() => res({ file: r.file, bytes: r.bytes }));
}));
ipcMain.handle("rec:open", (_e, file) => file ? shell.showItemInFolder(file) : shell.openPath(REC_DIR));

// ---------------- native game windows embedded in the app (Windows) ----------------
let embedder = null, embedQ = [], embedBuf = "";
function embedCmd(cmd) {
  if (process.platform !== "win32") return Promise.resolve({ ok: false });
  if (!embedder) {
    embedder = spawn(venvPython(), ["-u", path.join(__dirname, "winembed.py")], { windowsHide: true });
    embedder.stdout.on("data", d => { embedBuf += d; let i; while ((i = embedBuf.indexOf("\n")) >= 0) { const l = embedBuf.slice(0, i); embedBuf = embedBuf.slice(i + 1); const r = embedQ.shift(); r && r(JSON.parse(l)); } });
    embedder.on("close", () => { embedder = null; embedQ.splice(0).forEach(r => r({ ok: false })); });
  }
  return new Promise(res => { embedQ.push(res); embedder.stdin.write(JSON.stringify(cmd) + "\n"); });
}
let embedded = null;                                             // pid currently inside the app
ipcMain.handle("embed:sync", async (_e, st) => {
  // st: { pid, rect: {x,y,w,h} in window CSS px, visible }
  if (!st || !st.pid) { if (embedded) { await embedCmd({ op: "hide" }); } return { ok: true }; }
  if (embedded !== st.pid) {
    const parent = Number(win.getNativeWindowHandle().readBigUInt64LE(0));
    const r = await embedCmd({ op: "attach", pid: st.pid, parent });
    if (!r.ok) return r;
    embedded = st.pid;
  }
  if (!st.visible) return embedCmd({ op: "hide" });
  const k = screen.getDisplayMatching(win.getBounds()).scaleFactor;
  return embedCmd({ op: "move", x: Math.round(st.rect.x * k), y: Math.round(st.rect.y * k), w: Math.round(st.rect.w * k), h: Math.round(st.rect.h * k) });
});
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
    title: "G-Box · " + (title || "game"), icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true } });
  mini.loadFile(path.join(__dirname, "mini.html"), { query: { src: `${s.apiUrl}/api/sessions/${encodeURIComponent(sid)}/mjpeg?token=${encodeURIComponent(t)}`, title: title || "" } });
  mini.on("closed", () => { mini = null; if (win && !win.isDestroyed()) win.show(); });
  win.hide();
  return true;
});
ipcMain.handle("mini:aspect", (_e, w, h) => { if (mini && w && h) { mini.setAspectRatio(w / h); const [cw] = mini.getSize(); mini.setSize(cw, Math.round(cw * h / w)); } });
ipcMain.handle("mini:restore", () => { if (mini) mini.close(); });

// Screenshot of the whole app window (including the embedded G-Box view) as a PNG data URL.
ipcMain.handle("capture", async () => {
  const img = await win.webContents.capturePage();
  if (!img.isEmpty()) return img.toDataURL();
  const { width, height } = win.getContentBounds();             // fallback: OS-level capture of this window
  const srcs = await desktopCapturer.getSources({ types: ["window"], thumbnailSize: { width, height } });
  const me = srcs.find(s => s.id === win.getMediaSourceId()) || srcs.find(s => s.name === win.getTitle());
  return me ? me.thumbnail.toDataURL() : null;
});

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

// ---------------- window ----------------
app.setAppUserModelId("com.gbox.desktop");                 // taskbar groups under the G-Box icon
app.setName("G-Box");                                        // name in menus / about / notifications
app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_wc, perm, cb) => cb(["media", "audioCapture", "clipboard-read", "clipboard-sanitized-write"].includes(perm)));
  session.defaultSession.setPermissionCheckHandler((_wc, perm) => ["media", "audioCapture"].includes(perm));
  win = new BrowserWindow({
    width: 1500, height: 950, title: "G-Box", backgroundColor: "#16161a", autoHideMenuBar: true,
    icon: path.join(__dirname, "..", "..", "assets", "brand", "gbox.ico"),
    titleBarStyle: "hidden",                                         // custom title bar (capture + eyedropper icons)
    titleBarOverlay: { color: "#111114", symbolColor: "#e8e8ee", height: 36 },
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, webviewTag: true },
  });
  win.loadFile(path.join(__dirname, "index.html"));
  if (settings().autoStartWorker) setTimeout(startWorker, 1500);
});
app.on("window-all-closed", () => {
  try { embedder && embedder.stdin.write(JSON.stringify({ op: "detach" }) + "\n"); } catch {}
  for (const p of procs.values()) p.kill();
  if (worker) execFile("taskkill", ["/T", "/F", "/PID", String(worker.pid)]);
  app.quit();
});
