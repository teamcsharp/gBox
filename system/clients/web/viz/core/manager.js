// VisualizerManager: one shared WebGLRenderer, lazy mode instances, transitions (2 render targets + fullscreen quad),
// light bloom post, quality management. Everything per-frame reuses preallocated objects.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { FS_VERT, HASH, makeFSTri } from "./glsl.js";
import { SignalProcessor, createRaw, NB } from "./signal.js";
import { makePaletteUniforms, applyPalette, resolvePalette } from "./palettes.js";

export const QUALITY = {
  low: { level: 0, pr: 0.75, mult: 0.25, samples: 0 },
  medium: { level: 1, pr: 1.0, mult: 0.45, samples: 0 },
  high: { level: 2, pr: 1.5, mult: 0.7, samples: 4 },
  ultra: { level: 3, pr: 2.0, mult: 1.0, samples: 4 },
};
export const QUALITY_ORDER = ["low", "medium", "high", "ultra"];
export const DEFAULT_PRESET = { intensity: 1, speed: 1, audioSensitivity: 1, smoothing: 0.3, bloom: 0.8, opacity: 1, complexity: 1, motionAmount: 1 };

const COMPOSITE_FS = `
uniform sampler2D tA, tB; uniform float uP, uType; uniform vec3 uEdge;
varying vec2 vUv;
${HASH}
void main(){
  vec3 a = texture2D(tA, vUv).rgb;
  if (uP >= 1.0) { gl_FragColor = vec4(a, 1.0); return; }
  vec3 b = texture2D(tB, vUv).rgb;
  float p = clamp(uP, 0.0, 1.0);
  vec3 c;
  if (uType < 0.5) { c = mix(b, a, p * p * (3.0 - 2.0 * p)); }
  else if (uType < 1.5) {
    float n = vnoise(vUv * vec2(9.0, 5.0)) * 0.65 + vnoise(vUv * 48.0) * 0.35;
    float th = p * 1.2 - 0.1;
    float m = smoothstep(n - 0.03, n + 0.03, th);
    float edge = smoothstep(0.07, 0.0, abs(th - n));
    c = mix(b, a, m) + uEdge * edge * 1.4 * (1.0 - p);
  } else {
    c = p < 0.5 ? b * pow(1.0 - p * 2.0, 1.5) : a * pow(p * 2.0 - 1.0, 0.8);
  }
  gl_FragColor = vec4(c, 1.0);
}`;
const BRIGHT_FS = `
uniform sampler2D tIn; uniform vec2 uTexel; uniform float uThr;
varying vec2 vUv;
void main(){
  vec3 c = 0.25 * (texture2D(tIn, vUv + uTexel * vec2(-1.0, -1.0)).rgb + texture2D(tIn, vUv + uTexel * vec2(1.0, -1.0)).rgb +
                   texture2D(tIn, vUv + uTexel * vec2(-1.0, 1.0)).rgb + texture2D(tIn, vUv + uTexel * vec2(1.0, 1.0)).rgb);
  if (any(isnan(c))) c = vec3(0.0);
  c = clamp(c, 0.0, 32.0);
  float l = max(c.r, max(c.g, c.b));
  gl_FragColor = vec4(c * smoothstep(uThr, uThr + 0.4, l), 1.0);
}`;
const BLUR_FS = `
uniform sampler2D tIn; uniform vec2 uDir;
varying vec2 vUv;
void main(){
  vec3 c = texture2D(tIn, vUv).rgb * 0.2270270;
  c += (texture2D(tIn, vUv + uDir * 1.3846153).rgb + texture2D(tIn, vUv - uDir * 1.3846153).rgb) * 0.3162162;
  c += (texture2D(tIn, vUv + uDir * 3.2307692).rgb + texture2D(tIn, vUv - uDir * 3.2307692).rgb) * 0.0702702;
  gl_FragColor = vec4(c, 1.0);
}`;
const FINAL_FS = `
uniform sampler2D tIn, tBloom; uniform float uBloom, uTime;
varying vec2 vUv;
${HASH}
void main(){
  vec3 c = texture2D(tIn, vUv).rgb + texture2D(tBloom, vUv).rgb * uBloom;
  if (any(isnan(c))) c = vec3(0.0);
  c = max(c, 0.0);
  vec2 q = vUv - 0.5; c *= 1.0 - dot(q, q) * 0.35;
  vec3 k = max(c - 0.8, 0.0);
  c = min(c, vec3(0.8)) + 0.2 * (1.0 - exp(-k * 4.0));
  c += (hash12(gl_FragCoord.xy + fract(uTime) * 61.0) - 0.5) / 255.0;
  gl_FragColor = vec4(c, 1.0);
}`;

const sm = (cur, x, k, a) => cur + (Math.min(1, x * k) - cur) * a;

function postMat(fs, uniforms) {
  return new THREE.ShaderMaterial({ uniforms, vertexShader: FS_VERT, fragmentShader: fs, depthTest: false, depthWrite: false });
}

export class VisualizerManager {
  constructor(canvas, { presets = {}, quality = "auto", palette } = {}) {
    this.canvas = canvas;
    const r = this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, stencil: false, powerPreference: "high-performance" });
    r.outputColorSpace = THREE.LinearSRGBColorSpace; // palette colors are display values; no conversions
    r.setClearColor(0x000000, 1);
    r.info.autoReset = false;
    this.halfFloat = !!(r.capabilities.isWebGL2 && (r.extensions.has("EXT_color_buffer_float") || r.extensions.has("EXT_color_buffer_half_float")));

    this.presets = presets;
    this.signal = new SignalProcessor();
    this.raw = createRaw();
    this.provider = null;
    this.globals = { intensity: 1, speed: 1, sensitivity: 1 };

    this.pal = makePaletteUniforms();
    this.palTarget = makePaletteUniforms();
    this.paletteName = resolvePalette(palette);
    applyPalette(this.pal, this.paletteName); applyPalette(this.palTarget, this.paletteName);

    this.modes = new Map(); this.loading = new Map();
    this.active = null; this.trans = null; this.switchToken = 0;
    this.time = 0; this.running = false; this.raf = 0;
    this.fps = 60; this.fpsAcc = 0; this.fpsN = 0; this.lowSecs = 0; this.grace = 3;
    this.autoQ = quality === "auto";
    this.qualityName = this.autoQ ? (Math.min(window.devicePixelRatio || 1, 2) > 1.5 ? "medium" : "high") : (QUALITY[quality] ? quality : "high");

    // post
    this.postScene = new THREE.Scene(); this.postCam = new THREE.Camera();
    this.quad = makeFSTri(null); this.postScene.add(this.quad);
    this.matComp = postMat(COMPOSITE_FS, { tA: { value: null }, tB: { value: null }, uP: { value: 1 }, uType: { value: 0 }, uEdge: { value: this.pal.uC2.value } });
    this.matBright = postMat(BRIGHT_FS, { tIn: { value: null }, uTexel: { value: new THREE.Vector2() }, uThr: { value: 0.5 } });
    this.matBlur = postMat(BLUR_FS, { tIn: { value: null }, uDir: { value: new THREE.Vector2() } });
    this.matFinal = postMat(FINAL_FS, { tIn: { value: null }, tBloom: { value: null }, uBloom: { value: 0.8 }, uTime: { value: 0 } });
    this.ctx = { renderer: r, pal: this.pal, quality: this.qualityName, qmult: QUALITY[this.qualityName].mult, w: 1, h: 1, W: 1, H: 1, pr: 1 };
    this.makeTargets();
    this.resize();
    if (typeof ResizeObserver !== "undefined") { this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(canvas); }
    this.onWinResize = () => this.resize(); window.addEventListener("resize", this.onWinResize);
    this.loop = (now) => { if (!this.running) return; this.raf = requestAnimationFrame(this.loop); this.frame(now); };
  }

  makeTargets() {
    const q = QUALITY[this.qualityName];
    const type = this.halfFloat ? THREE.HalfFloatType : THREE.UnsignedByteType;
    [this.rtA, this.rtB, this.rtMix, this.rtB1, this.rtB2].forEach((t) => t && t.dispose());
    const samples = this.renderer.capabilities.isWebGL2 ? q.samples : 0;
    this.rtA = new THREE.WebGLRenderTarget(4, 4, { type, samples, depthBuffer: true });
    this.rtB = new THREE.WebGLRenderTarget(4, 4, { type, samples, depthBuffer: true });
    this.rtMix = new THREE.WebGLRenderTarget(4, 4, { type, depthBuffer: false });
    this.rtB1 = new THREE.WebGLRenderTarget(4, 4, { type, depthBuffer: false });
    this.rtB2 = new THREE.WebGLRenderTarget(4, 4, { type, depthBuffer: false });
  }

  resize() {
    const c = this.canvas;
    const w = Math.max(1, c.clientWidth || window.innerWidth), h = Math.max(1, c.clientHeight || window.innerHeight);
    const pr = Math.min(window.devicePixelRatio || 1, 2, QUALITY[this.qualityName].pr);
    const ctx = this.ctx;
    if (ctx.w === w && ctx.h === h && ctx.pr === pr && this.rtA.width > 4) return;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    const W = Math.max(1, Math.floor(w * pr)), H = Math.max(1, Math.floor(h * pr));
    Object.assign(ctx, { w, h, W, H, pr });
    this.rtA.setSize(W, H); this.rtB.setSize(W, H); this.rtMix.setSize(W, H);
    const bw = Math.max(1, W >> 2), bh = Math.max(1, H >> 2);
    this.rtB1.setSize(bw, bh); this.rtB2.setSize(bw, bh);
    this.matBright.uniforms.uTexel.value.set(1 / W, 1 / H);
    for (const m of this.modes.values()) m.resize(w, h, W, H);
  }

  setQuality(q) {
    this.autoQ = q === "auto";
    const name = this.autoQ ? this.qualityName : QUALITY[q] ? q : "high";
    this.applyQuality(name);
  }
  applyQuality(name) {
    const changedSamples = QUALITY[name].samples !== QUALITY[this.qualityName].samples;
    this.qualityName = name; this.ctx.quality = name; this.ctx.qmult = QUALITY[name].mult;
    if (changedSamples) this.makeTargets();
    this.ctx.w = -1; this.resize();
    for (const m of this.modes.values()) m.setQuality(name, Math.min(1, QUALITY[name].mult * (m.preset.complexity || 1)));
    this.lowSecs = 0; this.grace = 3;
  }

  setPalette(name, instant = false) {
    this.paletteName = resolvePalette(name);
    applyPalette(this.palTarget, this.paletteName);
    if (instant) applyPalette(this.pal, this.paletteName);
    this.palBlend = instant ? 0 : 1.2;
  }

  async setProvider(p) {
    if (this.provider && this.provider !== p) try { this.provider.stop(); } catch (e) {}
    this.provider = p;
    await p.start();
  }

  async getMode(id) {
    if (this.modes.has(id)) return this.modes.get(id);
    if (!this.loading.has(id)) {
      this.loading.set(id, (async () => {
        const mod = await import(new URL(`../modes/${id}.js`, import.meta.url).href);
        const m = new mod.default();
        m.id = id;
        m.preset = { ...DEFAULT_PRESET, ...(this.presets._default || {}), ...(this.presets[id] || {}) };
        m.params = { ...m.preset };
        m.view = { rms: 0, peak: 0, bass: 0, mid: 0, treble: 0, beat: 0, onset: false, speechActivity: 0, stationActivity: 0, energy: 0, time: 0, fft: new Float32Array(NB), src: null };
        m.init(this.ctx);
        m.setQuality(this.qualityName, Math.min(1, QUALITY[this.qualityName].mult * (m.preset.complexity || 1)));
        m.resize(this.ctx.w, this.ctx.h, this.ctx.W, this.ctx.H);
        this.modes.set(id, m);
        return m;
      })().finally(() => this.loading.delete(id)));
    }
    return this.loading.get(id);
  }

  async setMode(id, { transition = "crossfade", instant = false } = {}) {
    const token = ++this.switchToken;
    const mode = await this.getMode(id);
    if (token !== this.switchToken) return this.active && this.active.id;
    if (mode === this.active && !this.trans) return id;
    if (this.trans) { const f = this.trans.from; this.trans = null; if (f !== mode) f.deactivate(); }
    if (mode === this.active) return id;
    mode._pb = 1; // ignore the current beat level as a fresh impulse
    mode.activate();
    const prev = this.active;
    this.active = mode;
    if (!prev || instant) { if (prev) prev.deactivate(); }
    else this.trans = { from: prev, p: 0, dur: transition === "fade" ? 2.0 : 1.6, type: transition === "dissolve" ? 1 : transition === "fade" ? 2 : 0 };
    this.grace = Math.max(this.grace, 2);
    return id;
  }

  start() { if (this.running) return; this.running = true; this.last = performance.now(); this.raf = requestAnimationFrame(this.loop); }
  stop() { this.running = false; cancelAnimationFrame(this.raf); }

  trackFps(dt) {
    this.fpsAcc += dt; this.fpsN++;
    if (this.fpsAcc < 1) return;
    this.fps = this.fpsN / this.fpsAcc; this.fpsAcc = 0; this.fpsN = 0;
    if (this.grace > 0) { this.grace--; return; }
    if (!this.autoQ || document.hidden) return;
    if (this.fps < 45) {
      if (++this.lowSecs >= 3) {
        const i = QUALITY_ORDER.indexOf(this.qualityName);
        if (i > 0) this.applyQuality(QUALITY_ORDER[i - 1]); else this.lowSecs = 0;
      }
    } else this.lowSecs = 0;
  }

  step(m, S, dt) {
    const P = m.params, pre = m.preset, g = this.globals, v = m.view;
    P.intensity = pre.intensity * g.intensity; P.speed = pre.speed * g.speed; P.audioSensitivity = pre.audioSensitivity * g.sensitivity;
    P.smoothing = pre.smoothing; P.bloom = pre.bloom; P.opacity = pre.opacity; P.complexity = pre.complexity; P.motionAmount = pre.motionAmount;
    const k = P.audioSensitivity, tau = P.smoothing * 0.25, a = tau > 0 ? 1 - Math.exp(-dt / tau) : 1;
    v.rms = sm(v.rms, S.rms, k, a); v.peak = sm(v.peak, S.peak, k, a); v.bass = sm(v.bass, S.bass, k, a); v.mid = sm(v.mid, S.mid, k, a);
    v.treble = sm(v.treble, S.treble, k, a); v.energy = sm(v.energy, S.energy, k, a);
    v.speechActivity = S.speechActivity; v.stationActivity = S.stationActivity;
    v.beat = Math.min(1, S.beat * Math.min(1.5, k)); v.onset = S.onset; v.time = S.time; v.src = S;
    for (let i = 0; i < NB; i++) v.fft[i] = sm(v.fft[i], S.fft[i], k, a);
    m.update(v, dt * P.speed, dt);
  }

  frame(now) {
    let dt = (now - this.last) / 1000; this.last = now;
    if (!(dt > 0)) dt = 1 / 60;
    if (dt < 1) this.trackFps(dt); // real frame time (long gaps = hidden tab, ignored)
    if (dt > 0.1) dt = 0.1;
    const r = this.renderer;
    r.info.reset();
    this.time += dt;
    if (this.provider) this.provider.sample(this.time, dt, this.raw);
    const S = this.signal.process(this.raw, dt);
    if (this.palBlend > 0) { this.palBlend -= dt; applyPalette(this.pal, this.paletteName, Math.min(1, dt * 4)); }

    const tr = this.trans;
    if (tr) { tr.p += dt / tr.dur; if (tr.p >= 1) { tr.from.deactivate(); this.trans = null; } }
    const A = this.active;
    if (!A) { r.setRenderTarget(null); r.clear(); return; }
    this.step(A, S, dt);
    A.render(r, this.rtA);
    let bloom = A.params.bloom;
    const T = this.trans;
    if (T) {
      this.step(T.from, S, dt);
      T.from.render(r, this.rtB);
      bloom += (T.from.params.bloom - bloom) * (1 - T.p);
    }
    const q = this.quad, pc = this.postCam, ps = this.postScene;
    // composite
    const mc = this.matComp.uniforms;
    mc.tA.value = this.rtA.texture; mc.tB.value = this.rtB.texture; mc.uP.value = T ? T.p : 1; mc.uType.value = T ? T.type : 0;
    q.material = this.matComp; r.setRenderTarget(this.rtMix); r.render(ps, pc);
    // bloom: bright pass at 1/4 res, two separable blur iterations
    const bw = this.rtB1.width, bh = this.rtB1.height;
    if (bloom > 0.01) {
      this.matBright.uniforms.tIn.value = this.rtMix.texture;
      q.material = this.matBright; r.setRenderTarget(this.rtB1); r.render(ps, pc);
      q.material = this.matBlur;
      const bu = this.matBlur.uniforms;
      for (let i = 0; i < 2; i++) {
        const s = i + 1;
        bu.tIn.value = this.rtB1.texture; bu.uDir.value.set(s / bw, 0); r.setRenderTarget(this.rtB2); r.render(ps, pc);
        bu.tIn.value = this.rtB2.texture; bu.uDir.value.set(0, s / bh); r.setRenderTarget(this.rtB1); r.render(ps, pc);
      }
    }
    const fu = this.matFinal.uniforms;
    fu.tIn.value = this.rtMix.texture; fu.tBloom.value = this.rtB1.texture; fu.uBloom.value = bloom > 0.01 ? bloom : 0; fu.uTime.value = this.time;
    q.material = this.matFinal; r.setRenderTarget(null); r.render(ps, pc);
    if (this.onFrame) this.onFrame(dt, S);
  }

  dispose() {
    this.stop();
    if (this.ro) this.ro.disconnect();
    window.removeEventListener("resize", this.onWinResize);
    if (this.provider) try { this.provider.stop(); } catch (e) {}
    for (const m of this.modes.values()) try { m.dispose(); } catch (e) {}
    this.modes.clear();
    [this.rtA, this.rtB, this.rtMix, this.rtB1, this.rtB2].forEach((t) => t.dispose());
    [this.matComp, this.matBright, this.matBlur, this.matFinal].forEach((m) => m.dispose());
    this.quad.geometry.dispose();
    this.renderer.dispose();
  }
}
