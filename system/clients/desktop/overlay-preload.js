// Overlay swap window (swap-overlay.html, sandboxed): box / model / settings messages in, load status out. Nothing else.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("gboxOverlay", {
  on: fn => ipcRenderer.on("ov", (_e, m) => fn(m)),
  status: s => ipcRenderer.send("ov:status", s),
});
