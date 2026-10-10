// Overlay swap (Electron main process): a collection model drawn over the operator's on-screen character in the docked
// game, any game. Three parts:
//   overlay_track.py   (PC venv, OpenCV) prints the game window, tracks the character's box ~30x/s, one JSON line each
//   swap-overlay.html  (served from the API's /viz/, three.js) draws the model at that box: a transparent, click-through,
//                      never-focused window parented to the app window, kept exactly over the game picture
//   this file          glues them: box lines go straight to the overlay window (no work here beyond a JSON.parse)
// The renderer (index.html, OVL) decides what to show from the control plane record (GET /api/overlay/{sid}) and calls
// gbox.overlay(op, arg). A plain Alt+click on the game while it waits for a target marks the character (pick()).
const path = require("path");
const { spawn } = require("child_process");

module.exports = function overlaySwap({ app, ipcMain, BrowserWindow, getWin, venvPython, settings, token, send }) {
  let trk = null, buf = "", ov = null, ready = false, queue = [], st = null, hooked = null;

  function tracker(cmd) {
    if (!trk) {
      trk = spawn(venvPython(), ["-u", path.join(__dirname, "overlay_track.py")], { windowsHide: true });
      trk.stdout.on("data", d => {
        buf += d; let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const l = buf.slice(0, i); buf = buf.slice(i + 1);
          let m; try { m = JSON.parse(l); } catch { continue; }
          if (m.event === "box") { if (st && !st.awaiting) ovSend({ type: "box", box: m.box, ok: m.ok, bg: m.bg }); }
          else if (m.event === "stats") { if (st) { st.stats = m; status({}); } }
          else if (m.event === "state") {
            if (m.state === "capture" && m.mode === "screen" && ov && !ov.isDestroyed()) ov.setContentProtection(true);   // keep the model out of the tracker's view
            else status({ state: m.state, why: m.why || "" });
          }
        }
      });
      trk.stderr.on("data", d => send("task", "overlay", d.toString()));
      trk.on("close", code => { trk = null; buf = ""; if (st && !st.awaiting) status({ state: "error", why: `tracker exited (${code}): is opencv-contrib-python-headless in the PC venv?` }); });
    }
    trk.stdin.write(JSON.stringify(cmd) + "\n");
  }
  function status(x) {
    if (!st) return;
    Object.assign(st.status, x);
    send("overlay:status", { sid: st.sid, slug: st.slug, name: st.name, awaiting: !!st.awaiting, set: st.set, ...st.status,
                             fps: st.stats?.fps, cpu: st.stats?.cpu, grab_ms: st.stats?.grab_ms, track_ms: st.stats?.track_ms });
  }
  const ovSend = m => {
    if (st?.surface === "gpu") return send("embed:event", { event: "overlayframe", message: m });
    if (!ov || ov.isDestroyed()) return; if (ready) ov.webContents.send("ov", m); else queue.push(m);
  };

  async function ensureWindow() {
    const win = getWin();
    if (ov && !ov.isDestroyed()) return;
    ready = false; queue = [];
    ov = new BrowserWindow({ parent: win, frame: false, transparent: true, show: false, focusable: false, skipTaskbar: true, resizable: false,
                             movable: false, hasShadow: false, webPreferences: { preload: path.join(__dirname, "overlay-preload.js"),
                             contextIsolation: true, sandbox: true, backgroundThrottling: false } });
    ov.setIgnoreMouseEvents(true);
    ov.on("closed", () => { ov = null; ready = false; });
    if (hooked !== win) {                                  // follow the app window: moves, resizes, minimize / mini mode
      hooked = win;
      for (const ev of ["move", "resize", "restore", "show", "enter-full-screen", "leave-full-screen"]) win.on(ev, place);
      win.on("hide", () => ov && !ov.isDestroyed() && ov.hide());
      win.on("minimize", () => ov && !ov.isDestroyed() && ov.hide());
    }
    await ov.loadURL(settings().apiUrl + "/viz/swap-overlay.html");
  }
  ipcMain.on("ov:status", (_e, s) => {
    if (s.ready) { ready = true; queue.splice(0).forEach(m => ov.webContents.send("ov", m)); return; }
    if (s.loaded) status({ model: s.loaded, error: "" });
    if (s.error) status({ state: "error", why: "model: " + s.error });
  });

  // the game picture's rect in the app window (CSS px, from embedTick) minus the gBox panels over it (holes)
  function place() {
    const win = getWin();
    if (!win || !st) return;
    if (st.surface === "gpu") { if (ov && !ov.isDestroyed()) ov.hide(); return; }
    if (!ov || ov.isDestroyed()) return;
    if (!st.rect || !st.visible || win.isMinimized() || !win.isVisible()) { if (ov.isVisible()) ov.hide(); return; }
    const b = win.getContentBounds(), z = win.webContents.getZoomFactor() || 1, r = st.rect;
    const w = Math.max(1, Math.round(r.w * z)), h = Math.max(1, Math.round(r.h * z));
    ov.setBounds({ x: Math.round(b.x + r.x * z), y: Math.round(b.y + r.y * z), width: w, height: h });
    let shape = [{ x: 0, y: 0, width: w, height: h }];
    for (const o of st.holes || []) {                      // the model never draws over the chat / menus open on the game
      const hx = o.x * z, hy = o.y * z, hx2 = hx + o.w * z, hy2 = hy + o.h * z, next = [];
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
    try { ov.setShape(shape.map(s => ({ x: Math.round(s.x), y: Math.round(s.y), width: Math.max(1, Math.round(s.width)), height: Math.max(1, Math.round(s.height)) }))); } catch {}
    if (!ov.isVisible()) ov.showInactive();
  }

  function target(point) {                                // track what's at point (0..1 of the game picture), or ask for it
    if (point && point.length === 2 && point.every(v => typeof v === "number" && v >= 0 && v <= 1)) {
      st.awaiting = false;
      ovSend({ type: "banner", text: "" }); ovSend({ type: "reset" });
      tracker({ op: "start", pid: st.pid, point });
      status({ state: "starting", point });
    } else {
      st.awaiting = true;
      if (trk) tracker({ op: "stop" });
      ovSend({ type: "reset" });
      ovSend({ type: "banner", text: `Alt+click your character to put ${st.name || "the model"} over it` });
      status({ state: "picking" });
    }
  }

  ipcMain.handle("overlay", async (_e, op, a = {}) => {
    try {
      if (op === "start") {                               // a: {sid, pid, slug, name, point, newTarget, rect, visible, holes, set}
        const fresh = !st || st.sid !== a.sid || st.pid !== a.pid;
        if (fresh) st = { sid: a.sid, pid: a.pid, status: {}, set: {} };
        st.surface = a.surface || "native";
        if (st.surface === "gpu") { if (ov && !ov.isDestroyed()) ov.destroy(); }
        else await ensureWindow();
        Object.assign(st, { rect: a.rect || st.rect, visible: a.visible ?? st.visible ?? true, holes: a.holes || st.holes || [] });
        if (a.set) { st.set = { ...st.set, ...a.set }; ovSend({ type: "set", set: st.set }); }
        if (a.slug && a.slug !== st.slug) {
          st.slug = a.slug; st.name = a.name || a.slug;
          ovSend({ type: "model", slug: a.slug, api: settings().apiUrl, token: await token() });
        }
        place();
        if (fresh || a.newTarget) target(a.point);
        else status({});
        return { ok: true };
      }
      if (!st) return { ok: false, error: "no overlay" };
      if (op === "surface-status") {
        if (a.loaded) status({ model: a.loaded, error: "" });
        if (a.error) status({ state: "error", why: "model: " + a.error });
        return { ok: true };
      }
      if (op === "set") { st.set = { ...st.set, ...a }; ovSend({ type: "set", set: st.set }); status({}); return { ok: true }; }
      if (op === "pick") {
        if (st.surface !== "gpu" || !st.awaiting || a.sid !== st.sid) return { ok: false, error: "not awaiting this game's target" };
        if (!Array.isArray(a.point) || a.point.length !== 2 || !a.point.every(n => Number.isFinite(n) && n >= 0 && n <= 1))
          return { ok: false, error: "target outside game picture" };
        target(a.point); return { ok: true };
      }
      if (op === "repick") { target(a.point); return { ok: true }; }
      if (op === "rect") {
        const changed = st.surface !== (a.surface || "native"); st.surface = a.surface || "native";
        st.rect = a.rect; st.visible = !!a.visible; st.holes = a.holes || [];
        if (changed) {
          if (st.surface === "gpu") { if (ov && !ov.isDestroyed()) ov.destroy(); }
          else await ensureWindow();
          ovSend({ type: "model", slug: st.slug, api: settings().apiUrl, token: await token() });
          ovSend({ type: "set", set: st.set });
          ovSend({ type: "banner", text: st.awaiting ? `Alt+click your character to put ${st.name || 'the model'} over it` : "" });
        }
        place(); return { ok: true };
      }
      if (op === "stop") {
        if (trk) tracker({ op: "stop" });
        const was = st; st = null;
        if (ov && !ov.isDestroyed()) ov.destroy();
        ov = null; ready = false;
        send("embed:event", { event: "overlayframe", message: { type: "stop" } });
        send("overlay:status", { sid: was.sid, state: "stopped" });
        return { ok: true };
      }
      return { ok: false, error: "unknown op " + op };
    } catch (e) { return { ok: false, error: e.message }; }
  });

  app.on("will-quit", () => { try { trk && trk.stdin.write('{"op":"quit"}\n'); } catch {} });

  return {
    // a plain Alt+click on the docked game (x, y: DIP in the app window's content). True = it marked the overlay's target.
    pick(x, y) {
      if (!st || !st.awaiting || !st.rect) return false;
      const z = getWin()?.webContents.getZoomFactor() || 1, r = st.rect;
      const fx = (x / z - r.x) / r.w, fy = (y / z - r.y) / r.h;
      if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return false;
      target([fx, fy]);
      return true;
    },
  };
};
