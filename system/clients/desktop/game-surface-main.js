// A GPU capture is a presentation choice: it never launches, resets or stops a game.
const fs = require("node:fs");
const path = require("node:path");

module.exports = function gameSurfaceMain({ getWin, embedCmd, nativeSync, f3, frameDir, onCapture = () => {}, publishFrame }) {
  let current = null, queue = Promise.resolve();
  let publishing = false, latestFrame = null;
  function publish(sid, png) {
    if (!publishFrame || !sid) return;
    latestFrame = { sid, png };
    if (publishing) return;
    publishing = true;
    (async () => {
      try {
        while (latestFrame) {
          const next = latestFrame; latestFrame = null;
          await publishFrame(next.sid, next.png).catch(e => console.warn("Game frame publish:", e.message));
        }
      } finally { publishing = false; }
    })();
  }
  async function sync(st) {
    if (st?.surface === "gpu-ready") {
      if (!current || st.pid !== current.pid || st.sourceId !== current.sourceId)
        return { ok: false, error: "Stale game capture" };
      return embedCmd({ op: "captured", pid: st.pid });
    }
    if (st?.surface === "gpu-frame" || st?.surface === "gpu-track") {
      if (!current || st.pid !== current.pid || st.sourceId !== current.sourceId)
        return { ok: false, error: "Stale game frame" };
      if (!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(st.frame || "") || st.frame.length > 8 * 1024 * 1024)
        return { ok: false, error: "Invalid game frame" };
      const png = Buffer.from(st.frame.slice(st.frame.indexOf(",") + 1), "base64");
      if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])))
        return { ok: false, error: "Invalid PNG" };
      fs.mkdirSync(frameDir, { recursive: true });
      const tracking = st.surface === "gpu-track";
      const file = path.join(frameDir, `${current.pid}${tracking ? '.track' : ''}.png`), tmp = file + ".tmp";
      await fs.promises.writeFile(tmp, png);
      await fs.promises.rename(tmp, file);
      // Monitoring failure must not interrupt local gameplay.
      if (!tracking) publish(st.sid, png);
      return { ok: true, bytes: png.length };
    }
    if (st?.surface !== "gpu") {
      current = null;
      return nativeSync(st);
    }
    if (!Number.isSafeInteger(st.pid) || st.pid < 1 || !getWin() || getWin().isDestroyed())
      return { ok: false, error: "No active game window" };
    f3(true);
    const parent = Number(getWin().getNativeWindowHandle().readBigUInt64LE(0));
    const result = await embedCmd({ op: "capture", pid: st.pid, parent,
      w: st.rect?.w || 1280, h: st.rect?.h || 960, warm: !!st.warm });
    if (result.ok) { current = { pid: st.pid, sourceId: result.sourceId }; onCapture(st.pid); }
    return result;
  }
  return st => {
    const next = queue.then(() => sync(st));
    queue = next.catch(() => {});
    return next;
  };
};
