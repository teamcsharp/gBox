// Rasterize gbox-logo.svg (transparent) into PNG icons + a multi-size .ico using Electron's Chromium.
// Run: electron assets/brand/render.js   (re-run whenever the SVG changes)
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const dir = __dirname;
const svg = fs.readFileSync(path.join(dir, "gbox-logo.svg"), "utf8");
const SIZES = [16, 24, 32, 48, 64, 128, 256, 512];

async function render(size) {
  // square canvas, logo centred (the mark is taller than wide), fully transparent background
  const w = new BrowserWindow({ width: size, height: size, show: false, transparent: true, frame: false,
                                webPreferences: { offscreen: true } });
  const html = `<html><body style="margin:0;background:transparent;width:${size}px;height:${size}px;display:flex;
    align-items:center;justify-content:center;overflow:hidden">${svg.replace("<svg ", `<svg style="height:${size}px;width:auto" `)}</body></html>`;
  await w.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
  await new Promise(r => setTimeout(r, 300));
  const img = await w.webContents.capturePage({ x: 0, y: 0, width: size, height: size });
  w.destroy();
  return img.toPNG();
}

function ico(pngs) {   // ICO container with PNG payloads (supported since Vista)
  const head = Buffer.alloc(6 + 16 * pngs.length);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(pngs.length, 4);
  let off = head.length;
  pngs.forEach(([size, buf], i) => {
    const e = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, e); head.writeUInt8(size >= 256 ? 0 : size, e + 1);
    head.writeUInt16LE(1, e + 4); head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(buf.length, e + 8); head.writeUInt32LE(off, e + 12);
    off += buf.length;
  });
  return Buffer.concat([head, ...pngs.map(p => p[1])]);
}

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const { nativeImage } = require("electron");
  const master = nativeImage.createFromBuffer(await render(1024));     // render once, downscale with good filtering
  fs.writeFileSync(path.join(dir, "gbox-1024.png"), master.toPNG());
  const out = [];
  for (const s of SIZES) {
    const png = master.resize({ width: s, height: s, quality: "best" }).toPNG();
    fs.writeFileSync(path.join(dir, `gbox-${s}.png`), png);
    out.push([s, png]);
  }
  fs.writeFileSync(path.join(dir, "gbox.ico"), ico(out.filter(([s]) => s <= 256)));
  console.log("rendered", SIZES.join(","), "+ gbox.ico");
  app.quit();
});
