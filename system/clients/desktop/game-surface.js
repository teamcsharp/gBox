// The normal game belongs inside the guest DOM; PiP/fullscreen belong in the host DOM.
// Both are Chromium GPU video layers, so menus need no Win32 window regions.
const GPU_GAME = { pid: null, failedPid: null, source: null, checked: 0, frameAt: 0, retryAt: 0, error: null };
async function gpuGameGuest(wv) {
  if (!wv || wv.dataset.ready !== "true") return false;
  return wv.executeJavaScript(`(async () => {
    if (!window.GBoxGPUVideo) {
      if (!window.gboxGPUVideoLoading) window.gboxGPUVideoLoading = new Promise((resolve, reject) => {
        const s = document.createElement("script"); s.src = "/viz/gpu-game-surface.js";
        s.onload = resolve; s.onerror = () => { window.gboxGPUVideoLoading = null; s.remove(); reject(new Error("Game video module did not load")); };
        document.head.append(s);
      });
      await window.gboxGPUVideoLoading;
    }
    return window.GBoxGPUVideo.stats();
  })()`);
}
async function gpuGameDispose(wv = document.querySelector("#wv")) {
  window.GBoxGPUVideo?.dispose();
  await wv?.executeJavaScript("window.GBoxGPUVideo?.dispose()").catch(() => {});
  GPU_GAME.pid = null; GPU_GAME.source = null; EMB.surface = null;
}
async function gpuGamePresent(mine, rect, pipNow, hidden, wv, onPlay) {
  // RetroArch's network RetroPad is independent of HWND focus. Keep emulators whose
  // keyboard/controller bridges still require a native focused window on that path.
  if (mine.adapter !== "retroarch") return false;
  if (mine.detail.pid !== GPU_GAME.failedPid) GPU_GAME.retryAt = 0;
  if (Date.now() < GPU_GAME.retryAt) return false;
  try {
    const guestState = await gpuGameGuest(wv), rootState = window.GBoxGPUVideo.stats();
    const warm = !rootState.ready || rootState.pid !== mine.detail.pid;
    if (warm || GPU_GAME.pid !== mine.detail.pid || !GPU_GAME.source || Date.now() - GPU_GAME.checked > 2000) {
      const r = await gbox.embedSync({ surface: "gpu", pid: mine.detail.pid, rect, warm });
      if (!r.ok || !r.sourceId) throw new Error(r.error || "No game capture source");
      GPU_GAME.pid = mine.detail.pid; GPU_GAME.source = r.sourceId; GPU_GAME.checked = Date.now();
    }
    const st = { pid: GPU_GAME.pid, sid: mine.session_id, sourceId: GPU_GAME.source };
    const host = !!rect && (pipNow || VIEW.mode === "full");
    const visible = !!rect && !hidden && rect.h > 40;
    const root = await window.GBoxGPUVideo.sync({ ...st, host: "root", rect, visible: host && visible });
    if (!root.ready) throw new Error(root.error || "No decoded game frame");
    if (guestState) {
      if (!guestState.ready || guestState.pid !== st.pid || guestState.sourceId !== st.sourceId) {
        const offer = await window.GBoxGPUVideo.offer();
        const answer = await wv.executeJavaScript(`window.GBoxGPUVideo.receive(${JSON.stringify(st)}, ${JSON.stringify(offer)})`);
        await window.GBoxGPUVideo.answer(answer);
      }
      const guest = await wv.executeJavaScript(`window.GBoxGPUVideo.sync(${JSON.stringify({ ...st, external: true, visible: onPlay && !host })})`);
      if (!guest.ready) throw new Error(guest.error || "The game view could not display a frame");
    }
    if (warm) await gbox.embedSync({ ...st, surface: "gpu-ready" });
    EMB.surface = "gpu"; GPU_GAME.error = null; GPU_GAME.failedPid = null;
    EMB.vis = visible; EMB.holes = []; ovlRect();
    // Reports/agents need the game alone, even behind a dialog or while another tab
    // is open. One PNG/second is separate from the live video presentation path.
    if (Date.now() - GPU_GAME.frameAt > 1000) {
      const frame = window.GBoxGPUVideo.snapshot();
      if (frame) {
        const saved = await gbox.embedSync({ ...st, surface: "gpu-frame", frame });
        if (!saved.ok) throw new Error(saved.error || "Game screenshot could not be saved");
      }
      GPU_GAME.frameAt = Date.now();
    }
    return true;
  } catch (e) {
    GPU_GAME.error = e.message; GPU_GAME.failedPid = mine.detail.pid; GPU_GAME.retryAt = Date.now() + 30000;
    console.warn("GPU game view; restoring native dock:", e.message);
    await gpuGameDispose(wv); EMB.last = "";
    return false;
  }
}
let gpuOverlaySending = false, gpuOverlayBox = null;
async function gpuGameOverlay(message) {
  const url = S.apiUrl + "/viz/swap-overlay.html";
  window.GBoxGPUVideo.overlay(message, url);
  const wv = document.querySelector("#wv");
  if (wv?.dataset.ready === "true") await wv.executeJavaScript(`window.GBoxGPUVideo?.overlay(${JSON.stringify(message)}, ${JSON.stringify(url)})`).catch(() => {});
}
function gpuGameOverlayEvent(message) {
  if (message.type !== "box") { gpuGameOverlay(message); return; }
  gpuOverlayBox = message;
  if (gpuOverlaySending) return;
  gpuOverlaySending = true;
  (async () => {
    try { while (gpuOverlayBox) { const m = gpuOverlayBox; gpuOverlayBox = null; await gpuGameOverlay(m); } }
    finally { gpuOverlaySending = false; }
  })();
}
let gpuTrackingFrame = false;
setInterval(async () => {
  if (gpuTrackingFrame || EMB.surface !== "gpu" || !OVL.rec?.on) return;
  gpuTrackingFrame = true;
  try {
    const frame = window.GBoxGPUVideo.snapshot(240);
    if (frame) await gbox.embedSync({ surface: "gpu-track", pid: EMB.pid, sourceId: GPU_GAME.source, frame });
  } catch (e) { console.warn("Game tracking frame:", e.message); }
  finally { gpuTrackingFrame = false; }
}, 66);
function gpuGameVoice(st) {
  const url = S.apiUrl + "/viz/overlay.html";
  window.GBoxGPUVideo.voice(st, url);
  const wv = document.querySelector("#wv");
  if (wv?.dataset.ready === "true") wv.executeJavaScript(`window.GBoxGPUVideo?.voice(${JSON.stringify(st)}, ${JSON.stringify(url)})`).catch(() => {});
}
async function gpuGamePick(x, y) {
  const pick = (v, x, y) => {
    if (!v) return null;
    const r = v.getBoundingClientRect(), scale = Math.min(r.width / v.videoWidth, r.height / v.videoHeight);
    const w = v.videoWidth * scale, h = v.videoHeight * scale;
    const point = [(x - r.left - (r.width - w) / 2) / w, (y - r.top - (r.height - h) / 2) / h];
    return point.every(n => Number.isFinite(n) && n >= 0 && n <= 1) ? point : null;
  };
  let point;
  const rootVideo = document.querySelector("#gpu-game");
  if (rootVideo?.style.display === "block") point = pick(rootVideo, x, y);
  else {
    const wv = document.querySelector("#wv"), r = wv?.getBoundingClientRect();
    if (r && wv.dataset.ready === "true") point = await wv.executeJavaScript(`(${pick.toString()})(document.querySelector('#nativeslot video'), ${JSON.stringify(x - r.left)}, ${JSON.stringify(y - r.top)})`);
  }
  if (point) return gbox.overlay("pick", { sid: EMB.sid, point });
}
let gpuWhipCanvas = null, gpuWhip = null;
async function gpuGameWhip(ev) {
  if (EMB.surface !== "gpu") { gpuWhipCanvas?.remove(); gpuWhipCanvas = gpuWhip = null; return; }
  if (ev.phase === "start") {
    gpuWhipCanvas?.remove();
    gpuWhipCanvas = document.createElement("canvas"); gpuWhipCanvas.id = "gpu-whip";
    gpuWhipCanvas.width = innerWidth; gpuWhipCanvas.height = innerHeight;
    Object.assign(gpuWhipCanvas.style, { position: "fixed", inset: "0", pointerEvents: "none", zIndex: "89" });
    document.body.append(gpuWhipCanvas); gpuWhip = { a: [ev.x, ev.y] };
  }
  if (!gpuWhip || !gpuWhipCanvas) return;
  const c = gpuWhipCanvas, g = c.getContext("2d"), a = gpuWhip.a, b = [ev.x, ev.y];
  g.clearRect(0, 0, c.width, c.height); g.strokeStyle = "#ff3b3b"; g.lineWidth = 4; g.lineCap = "round";
  g.shadowColor = "#000"; g.shadowBlur = 6; g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.stroke();
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  g.beginPath(); g.moveTo(b[0] - 18 * Math.cos(angle - .4), b[1] - 18 * Math.sin(angle - .4));
  g.lineTo(...b); g.lineTo(b[0] - 18 * Math.cos(angle + .4), b[1] - 18 * Math.sin(angle + .4)); g.stroke();
  for (const [x, y] of [a, b]) { g.beginPath(); g.arc(x, y, 12, 0, Math.PI * 2); g.stroke(); }
  if (ev.phase !== "end") return;
  gpuWhip = null;
  try {
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 12) { c.remove(); return await gpuGamePick(...a); }
    await new Promise(r => setTimeout(r, 60));
    const shot = await gbox.captureOS().catch(() => null);
    c.remove();
    await whipSend({ event: "whip", phase: "end", a, b, shot });
  } finally { c.remove(); if (gpuWhipCanvas === c) gpuWhipCanvas = null; }
}
