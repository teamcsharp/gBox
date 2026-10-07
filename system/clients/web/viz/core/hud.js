// Debug HUD (DOM overlay). Created only on demand.
const FIELDS = ["rms", "peak", "bass", "mid", "treble", "beat", "speechActivity", "stationActivity", "energy"];

export class Hud {
  constructor(ctl, mgr) {
    this.ctl = ctl; this.mgr = mgr; this.acc = 1;
    const el = this.el = document.createElement("div");
    el.className = "gbviz-hud";
    el.style.cssText = "position:fixed;left:10px;top:10px;z-index:2147483000;width:260px;padding:10px 12px;border-radius:10px;" +
      "background:rgba(4,10,28,.78);border:1px solid rgba(80,170,255,.35);color:#cfe6ff;font:11px/1.35 ui-monospace,Consolas,monospace;" +
      "backdrop-filter:blur(6px);box-shadow:0 6px 24px rgba(0,0,0,.4);user-select:none;";
    el.innerHTML = `<div data-k="head" style="font-weight:600;color:#fff;margin-bottom:6px"></div>
      <div data-k="bars"></div>
      <canvas data-k="fft" width="236" height="40" style="display:block;margin:6px 0;width:236px;height:40px;background:rgba(0,0,0,.35);border-radius:4px"></canvas>
      <div data-k="info" style="white-space:pre;color:#9fc4ec"></div>
      <div data-k="sliders" style="margin-top:6px"></div>
      <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap" data-k="btns"></div>`;
    const q = (k) => el.querySelector(`[data-k="${k}"]`);
    this.head = q("head"); this.info = q("info"); this.fftc = q("fft").getContext("2d");
    this.bars = {};
    for (const f of FIELDS) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:6px;height:13px";
      row.innerHTML = `<span style="width:92px;color:#8fb3da">${f}</span><span style="flex:1;height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden"><i style="display:block;height:100%;width:0;background:linear-gradient(90deg,#1f56e8,#2fd2ff)"></i></span><b style="width:30px;text-align:right;font-weight:400"></b>`;
      q("bars").appendChild(row);
      this.bars[f] = { bar: row.querySelector("i"), val: row.querySelector("b") };
    }
    const g = mgr.globals;
    for (const [key, label, max] of [["intensity", "intensity", 2], ["speed", "speed", 3], ["sensitivity", "sensitivity", 3]]) {
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:6px";
      row.innerHTML = `<span style="width:72px;color:#8fb3da">${label}</span><input type="range" min="0" max="${max}" step="0.05" value="${g[key]}" style="flex:1"><b style="width:30px;text-align:right;font-weight:400">${g[key].toFixed(2)}</b>`;
      const inp = row.querySelector("input"), b = row.querySelector("b");
      inp.addEventListener("input", () => { g[key] = +inp.value; b.textContent = g[key].toFixed(2); });
      q("sliders").appendChild(row);
    }
    const btn = (label, fn) => {
      const b = document.createElement("button"); b.textContent = label;
      b.style.cssText = "background:rgba(47,210,255,.12);color:#cfe6ff;border:1px solid rgba(47,210,255,.4);border-radius:5px;padding:2px 7px;font:inherit;cursor:pointer";
      b.addEventListener("click", fn); q("btns").appendChild(b);
    };
    btn("demo", () => ctl.setProvider("demo"));
    btn("mic", () => ctl.setProvider("mic").catch((e) => console.warn("[viz] mic:", e)));
    btn("quality", () => { const o = ["auto", "low", "medium", "high", "ultra"]; const cur = mgr.autoQ ? "auto" : mgr.qualityName; ctl.setQuality(o[(o.indexOf(cur) + 1) % o.length]); });
    btn("beat", () => ctl.push({ beat: 1 }));
    document.body.appendChild(el);
  }
  update(dt, S) {
    this.acc += dt;
    if (this.acc < 0.1) return;
    this.acc = 0;
    const m = this.mgr, a = m.active;
    this.head.textContent = `${m.fps.toFixed(0)} fps  ${a ? a.id : "-"}${m.trans ? " (transition)" : ""}`;
    for (const f of FIELDS) { const v = S[f] || 0; this.bars[f].bar.style.width = (Math.min(1, v) * 100).toFixed(1) + "%"; this.bars[f].val.textContent = v.toFixed(2); }
    const c = this.fftc; c.clearRect(0, 0, 236, 40); c.fillStyle = "#2fd2ff";
    for (let i = 0; i < S.fft.length; i++) { const h = S.fft[i] * 38; c.fillRect(i * (236 / S.fft.length), 40 - h, 236 / S.fft.length - 1, h); }
    const st = a ? a.stats() : { objects: 0, particles: 0 }, ri = m.renderer.info;
    const prov = m.provider ? m.provider.kind + (m.provider.scene ? ` [${m.provider.scene}]` : "") : "-";
    this.info.textContent = `quality ${m.autoQ ? "auto:" : ""}${m.qualityName}  pr ${m.ctx.pr.toFixed(2)}  ${m.ctx.W}x${m.ctx.H}\n` +
      `palette ${m.paletteName}\nprovider ${prov}\nobjects ${st.objects}  particles ${st.particles}\n` +
      `calls ${ri.render.calls}  tris ${ri.render.triangles}  pts ${ri.render.points}\n` +
      `geoms ${ri.memory.geometries}  tex ${ri.memory.textures}  progs ${ri.programs ? ri.programs.length : 0}`;
  }
  dispose() { this.el.remove(); }
}
