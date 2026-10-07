// 3 Line Spectrum: stacked luminous contour lines (spectral waterfall + noise + neighbour coupling) with spectrum ticks.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { PAL_DECL, makeBackdrop, makeFFTTexture } from "../core/glsl.js";
import { noise2, smoothstep, Spring } from "../core/util.js";

const LMAX = 50, P = 220, NB = 64, HH = 4; // half height of the ortho view

const VS = `attribute float aLine, aSide, aAmp; varying float vLine, vSide, vAmp;
void main(){ vLine = aLine; vSide = aSide; vAmp = aAmp; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const FS = `${PAL_DECL} uniform float uBright; varying float vLine, vSide, vAmp;
void main(){
  float s = abs(vSide);
  float core = exp(-s * s * 16.0), halo = exp(-s * s * 3.0) * 0.3;
  vec3 c = mix(uC2, uC3, vLine);
  c = mix(c, uHi, clamp(vAmp * 0.9, 0.0, 1.0) * core);
  float calm = 0.45 + 0.55 * smoothstep(0.08, 0.4, abs(vLine - 0.5));   // dimmer around the vertical centre (title area)
  float a = (core + halo) * (0.4 + 0.9 * clamp(vAmp, 0.0, 1.0)) * uBright * calm;
  gl_FragColor = vec4(c, a);
}`;
const TICK_VS = `uniform sampler2D uFFT; uniform float uW, uTickH, uThick; attribute float aIdx; varying float vY; varying float vF;
void main(){
  float f = texture2D(uFFT, vec2((aIdx + 0.5) / 64.0, 0.5)).r;
  vF = f; vY = position.y;
  vec3 p = vec3(mix(-uW, uW, (aIdx + 0.5) / 64.0) + position.x * uThick, -${HH}.0 + position.y * (0.05 + f * uTickH), 0.5);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const TICK_FS = `${PAL_DECL} uniform float uTickA; varying float vY; varying float vF;
void main(){ gl_FragColor = vec4(mix(uC2, uHi, vY * vF), uTickA * (1.0 - vY * 0.7) * (0.3 + vF)); }`;

export default class LineSpectrum extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera = new THREE.OrthographicCamera(-HH, HH, HH, -HH, -10, 10);
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    const nv = LMAX * P * 2;
    this.pos = new Float32Array(nv * 3); this.amp = new Float32Array(nv);
    const line = new Float32Array(nv), side = new Float32Array(nv), idx = new Uint32Array(LMAX * (P - 1) * 6);
    for (let v = 0; v < nv; v++) side[v] = v & 1 ? 1 : -1;
    let k = 0;
    for (let l = 0; l < LMAX; l++) for (let p = 0; p < P - 1; p++) {
      const a = (l * P + p) * 2; idx[k++] = a; idx[k++] = a + 1; idx[k++] = a + 2; idx[k++] = a + 1; idx[k++] = a + 3; idx[k++] = a + 2;
    }
    const g = this.geo = new THREE.BufferGeometry();
    this.posAttr = new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage);
    this.ampAttr = new THREE.BufferAttribute(this.amp, 1).setUsage(THREE.DynamicDrawUsage);
    this.lineAttr = new THREE.BufferAttribute(line, 1);
    g.setAttribute("position", this.posAttr); g.setAttribute("aAmp", this.ampAttr); g.setAttribute("aLine", this.lineAttr); g.setAttribute("aSide", new THREE.BufferAttribute(side, 1));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    this.lineU = { ...ctx.pal, uBright: { value: 1 } };
    this.mesh = new THREE.Mesh(g, new THREE.ShaderMaterial({ uniforms: this.lineU, vertexShader: VS, fragmentShader: FS, transparent: true, side: THREE.DoubleSide, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending }));
    this.mesh.frustumCulled = false; this.scene.add(this.mesh);
    // simulation state
    this.hist = new Float32Array(LMAX * NB); this.head = 0; this.histT = 0;
    this.tgt = new Float32Array(LMAX * P); this.h = new Float32Array(LMAX * P);
    this.ys = new Float32Array(P); this.xs = new Float32Array(P);
    // spectrum ticks
    this.fft = makeFFTTexture();
    const tg = new THREE.InstancedBufferGeometry();
    const plane = new THREE.PlaneGeometry(1, 1); plane.translate(0, 0.5, 0);
    tg.index = plane.index; tg.setAttribute("position", plane.getAttribute("position"));
    const ai = new Float32Array(NB); for (let i = 0; i < NB; i++) ai[i] = i;
    tg.setAttribute("aIdx", new THREE.InstancedBufferAttribute(ai, 1)); tg.instanceCount = NB;
    this.tickU = { ...ctx.pal, uFFT: { value: this.fft.tex }, uW: { value: 6 }, uTickH: { value: 1.6 }, uThick: { value: 0.01 }, uTickA: { value: 0 } };
    this.ticks = new THREE.Mesh(tg, new THREE.ShaderMaterial({ uniforms: this.tickU, vertexShader: TICK_VS, fragmentShader: TICK_FS, transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending }));
    this.ticks.frustumCulled = false; this.scene.add(this.ticks);
    this.tickVis = new Spring(4, 3.5, 0); this.tickTimer = 4;
    this.W = 6; this.thick = 0.02; this.L = 30;
  }
  setQuality(q, mult) {
    this.L = Math.round(20 + 30 * mult);
    const L = this.L, line = this.lineAttr.array;
    for (let l = 0; l < LMAX; l++) for (let v = 0; v < P * 2; v++) line[l * P * 2 + v] = Math.min(1, l / (L - 1));
    this.lineAttr.needsUpdate = true;
    this.geo.setDrawRange(0, L * (P - 1) * 6);
    this.particles = L * P;
  }
  resize(w, h, W, H) {
    const a = w / h, c = this.camera;
    c.left = -HH * a; c.right = HH * a; c.top = HH; c.bottom = -HH; c.updateProjectionMatrix();
    this.W = HH * a * 1.02;
    this.thick = (3.2 * 2 * HH) / Math.max(200, h); // ~3.2 css px half-width strip (core ~1px + halo)
    this.tickU.uW.value = HH * a * 0.94; this.tickU.uThick.value = (1.2 * 2 * HH) / Math.max(200, h);
  }
  update(s, dt, rdt) {
    const Pm = this.params;
    this.t += dt;
    const t = this.t, L = this.L, W = this.W;
    // spectral history (waterfall): bottom line = newest
    this.histT += dt;
    while (this.histT > 0.075) { this.histT -= 0.075; this.head = (this.head + 1) % LMAX; this.hist.set(s.fft, this.head * NB); }
    const hit = this.beatHit(s);
    const amp = 0.55 * Pm.intensity, bass = s.bass, tre = s.treble;
    const tgt = this.tgt, hh = this.h;
    for (let l = 0; l < L; l++) {
      const ln = l / (L - 1), yb = -HH * 0.86 + ln * HH * 1.72;
      const calm = 0.3 + 0.7 * smoothstep(0.12, 0.5, Math.abs(yb) / HH);
      const row = ((this.head - l + LMAX) % LMAX) * NB;
      for (let p = 0; p < P; p++) {
        const xn = (p / (P - 1)) * 2 - 1, x = xn * W;
        const fb = ((xn + 1) * 0.5) * 58, i0 = fb | 0, fr = fb - i0;
        const spec = this.hist[row + i0] * (1 - fr) + this.hist[row + Math.min(63, i0 + 1)] * fr;
        const env = smoothstep(1, 0.7, Math.abs(xn));
        const n = noise2(x * 0.35 + t * 0.25, l * 0.3 - t * 0.12) * 0.32 * (0.6 + 0.6 * bass) * Pm.motionAmount +
          noise2(x * 1.4 - t * 0.7, l * 0.9) * 0.07 * (0.2 + tre);
        tgt[l * P + p] = (n + spec * 1.5 * (1 + hit * 0.5)) * env * calm;
      }
    }
    // neighbour coupling + inertia, then build strips
    const a = 1 - Math.exp(-rdt / 0.06), pos = this.pos, am = this.amp, th = this.thick, xs = this.xs, ys = this.ys;
    for (let l = 0; l < L; l++) {
      const ln = l / (L - 1), yb = -HH * 0.86 + ln * HH * 1.72;
      const lo = l > 0 ? l - 1 : l, hi = l < L - 1 ? l + 1 : l;
      for (let p = 0; p < P; p++) {
        const i = l * P + p;
        const c = 0.5 * tgt[i] + 0.25 * (tgt[lo * P + p] + tgt[hi * P + p]);
        hh[i] += (c - hh[i]) * a;
        xs[p] = ((p / (P - 1)) * 2 - 1) * W;
        ys[p] = yb + hh[i] * amp;
      }
      for (let p = 0; p < P; p++) {
        const p0 = p > 0 ? p - 1 : p, p1 = p < P - 1 ? p + 1 : p;
        let nx = -(ys[p1] - ys[p0]), ny = xs[p1] - xs[p0];
        const len = Math.hypot(nx, ny) || 1; nx = (nx / len) * th; ny = (ny / len) * th;
        const v = (l * P + p) * 2, o = v * 3;
        pos[o] = xs[p] - nx; pos[o + 1] = ys[p] - ny; pos[o + 2] = 0;
        pos[o + 3] = xs[p] + nx; pos[o + 4] = ys[p] + ny; pos[o + 5] = 0;
        const e = Math.abs(hh[l * P + p]) * 1.3;
        am[v] = e; am[v + 1] = e;
      }
    }
    this.posAttr.needsUpdate = true; this.ampAttr.needsUpdate = true;
    this.lineU.uBright.value = (0.8 + s.rms * 0.4) * Pm.opacity;
    // occasional ticks
    this.tickTimer -= dt;
    if (this.tickTimer < 0 || hit > 0.8) { this.tickOn = !this.tickOn || hit > 0.8; this.tickTimer = this.tickOn ? 3 + Math.random() * 3 : 5 + Math.random() * 6; }
    this.tickU.uTickA.value = Math.max(0, this.tickVis.step(this.tickOn ? 0.55 : 0, rdt));
    this.fft.update(s.fft);
    this.bg.material.uniforms.uTime.value = t;
  }
}
