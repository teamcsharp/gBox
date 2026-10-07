// 7 Audio Bars: instanced translucent columns with bright caps, slowly falling peak-hold markers,
// glossy reflective floor, slightly elevated slowly drifting camera. Bass at the edges, treble in the (calm) centre.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { PAL_DECL, makeBackdrop } from "../core/glsl.js";

const MAX = 128;

const BAR_VS = `
uniform float uN, uSpan, uMaxH, uBarW, uMirror;
attribute float aIdx, aH;
varying float vWY, vTop, vH, vX; varying vec3 vN;
void main(){
  float x = ((aIdx + 0.5) / uN - 0.5) * uSpan;
  float h = 0.04 + aH * uMaxH;
  vec3 p = vec3(position.x * uBarW + x, position.y * h, position.z * uBarW);
  vWY = p.y; vTop = h; vH = aH; vX = aIdx / uN; vN = normal;
  if (uMirror > 0.5) p.y = -p.y;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const BAR_FS = `${PAL_DECL}
uniform float uMirror, uAlpha, uBeat;
varying float vWY, vTop, vH, vX; varying vec3 vN;
void main(){
  float k = clamp(vWY / 4.0, 0.0, 1.0);
  vec3 c = mix(uC1, uC2, k * 1.1 + vH * 0.3);
  float cap = step(vTop - 0.1, vWY);
  float side = vN.z > 0.5 ? 1.0 : vN.y > 0.5 ? 1.25 : 0.62;
  c = c * side;
  c = mix(c, uHi, cap * 0.85);
  float edge = vN.z > 0.5 ? 0.0 : 0.0;
  float a = (0.42 + 0.25 * k + cap * 0.5) * uAlpha * (1.0 + uBeat * 0.3);
  if (uMirror > 0.5) { a *= 0.32 * (1.0 - smoothstep(0.0, 2.6, vWY)); }
  gl_FragColor = vec4(c, a);
}`;
const PK_VS = `
uniform float uN, uSpan, uMaxH, uBarW;
attribute float aIdx, aPk;
varying float vPk;
void main(){
  float x = ((aIdx + 0.5) / uN - 0.5) * uSpan;
  vec3 p = vec3(position.x * uBarW * 1.1 + x, 0.1 + aPk * uMaxH + 0.12 + position.y * 0.06, position.z * uBarW * 1.1);
  vPk = aPk;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const PK_FS = `${PAL_DECL} varying float vPk; void main(){ gl_FragColor = vec4(mix(uC2, uHi, 0.7), 0.35 + vPk * 0.65); }`;
const FLOOR_VS = `varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;
const FLOOR_FS = `${PAL_DECL} uniform float uTime, uSpan, uGlow; varying vec3 vW;
void main(){
  float d = length(vW.xz * vec2(0.6, 1.0));
  vec3 c = mix(uBg1 * 0.5, uBg0, smoothstep(2.0, 24.0, d));
  vec2 g = abs(fract(vW.xz * 0.5) - 0.5) / fwidth(vW.xz * 0.5);
  float line = 1.0 - min(min(g.x, g.y), 1.0);
  c += uC1 * line * 0.12 * exp(-d * 0.08);
  float streak = exp(-abs(vW.z - 1.5) * 1.2) * smoothstep(uSpan * 0.6, 0.0, abs(vW.x));
  c += uC2 * streak * (0.05 + uGlow * 0.12);
  float a = 0.78 * smoothstep(40.0, 18.0, d);
  gl_FragColor = vec4(c, a);
}`;

export default class AudioBars extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.fov = 45;
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    const box = new THREE.BoxGeometry(1, 1, 1); box.translate(0, 0.5, 0);
    const mk = () => { const g = new THREE.InstancedBufferGeometry(); g.index = box.index; g.setAttribute("position", box.getAttribute("position")); g.setAttribute("normal", box.getAttribute("normal")); return g; };
    const idx = new Float32Array(MAX); for (let i = 0; i < MAX; i++) idx[i] = i;
    this.hA = new THREE.InstancedBufferAttribute(new Float32Array(MAX), 1).setUsage(THREE.DynamicDrawUsage);
    this.pA = new THREE.InstancedBufferAttribute(new Float32Array(MAX), 1).setUsage(THREE.DynamicDrawUsage);
    const iA = new THREE.InstancedBufferAttribute(idx, 1);
    this.gBar = mk(); this.gBar.setAttribute("aIdx", iA); this.gBar.setAttribute("aH", this.hA);
    this.gPk = mk(); this.gPk.setAttribute("aIdx", iA); this.gPk.setAttribute("aPk", this.pA);
    this.common = { uN: { value: 64 }, uSpan: { value: 20 }, uMaxH: { value: 4.2 }, uBarW: { value: 0.2 } };
    const bu = (mirror) => ({ ...ctx.pal, ...this.common, uMirror: { value: mirror }, uAlpha: { value: 1 }, uBeat: { value: 0 } });
    const mkMat = (vs, fs, u, extra = {}) => new THREE.ShaderMaterial({ uniforms: u, vertexShader: vs, fragmentShader: fs, transparent: true, ...extra });
    this.mirror = new THREE.Mesh(this.gBar, mkMat(BAR_VS, BAR_FS, bu(1), { depthWrite: false, blending: THREE.AdditiveBlending }));
    this.bars = new THREE.Mesh(this.gBar, mkMat(BAR_VS, BAR_FS, bu(0), { depthWrite: false }));
    this.peaks = new THREE.Mesh(this.gPk, mkMat(PK_VS, PK_FS, { ...ctx.pal, ...this.common }, { depthWrite: false, blending: THREE.AdditiveBlending }));
    this.floorU = { ...ctx.pal, uTime: { value: 0 }, uSpan: this.common.uSpan, uGlow: { value: 0 } };
    const fm = mkMat(FLOOR_VS, FLOOR_FS, this.floorU, { depthWrite: false }); fm.extensions.derivatives = true;
    this.floor = new THREE.Mesh(new THREE.PlaneGeometry(120, 120), fm); this.floor.rotation.x = -Math.PI / 2;
    [this.mirror, this.floor, this.bars, this.peaks].forEach((m, i) => { m.renderOrder = i + 1; m.frustumCulled = false; this.scene.add(m); });
    this.h = this.hA.array; this.pk = this.pA.array; this.hold = new Float32Array(MAX); this.pv = new Float32Array(MAX);
    this.N = 64;
  }
  setQuality(q, mult) {
    this.Nq = [48, 64, 96, 128][Math.min(3, Math.round(mult * 4 - 0.6))] || 64;
    this.applyN();
  }
  applyN() {
    const a = this.camera.aspect || 1.7;
    this.N = a < 1.2 ? Math.min(this.Nq, 48) : this.Nq; // narrow / portrait screens: fewer, wider bars
    this.gBar.instanceCount = this.gPk.instanceCount = this.N; this.common.uN.value = this.N;
    this.particles = this.N;
    this.layout();
  }
  layout() {
    const c = this.camera, dist = 15;
    const visW = 2 * Math.tan((c.fov * Math.PI) / 360) * dist * c.aspect;
    this.common.uSpan.value = Math.min(visW * 0.9, 34);
    this.common.uBarW.value = (this.common.uSpan.value / this.N) * 0.62;
  }
  resize(w, h) { super.resize(w, h); if (this.Nq) this.applyN(); }
  update(s, dt, rdt) {
    const P = this.params, N = this.N, h = this.h, pk = this.pk, fft = s.fft;
    this.t += dt;
    const ka = 1 - Math.exp(-rdt / 0.025), kd = 1 - Math.exp(-rdt / 0.32);
    for (let i = 0; i < N; i++) {
      const e = Math.abs((i / (N - 1)) * 2 - 1);
      const fb = 2 + (1 - e) * 56, i0 = fb | 0, fr = fb - i0;
      const f = fft[i0] * (1 - fr) + fft[i0 + 1] * fr;
      const idle = 0.035 + 0.03 * (0.5 + 0.5 * Math.sin(this.t * 1.3 + i * 0.35)) * P.motionAmount;
      const tgt = Math.min(1, Math.pow(f, 0.85) * (0.75 + 0.35 * e) * P.intensity + idle);
      h[i] += (tgt - h[i]) * (tgt > h[i] ? ka : kd);
      if (h[i] >= pk[i]) { pk[i] = h[i]; this.hold[i] = 0.7; this.pv[i] = 0; }
      else if ((this.hold[i] -= rdt) < 0) { this.pv[i] += rdt * 0.5; pk[i] = Math.max(h[i], pk[i] - this.pv[i] * rdt); }
    }
    this.hA.needsUpdate = true; this.pA.needsUpdate = true;
    const beat = s.beat;
    this.bars.material.uniforms.uBeat.value = beat; this.bars.material.uniforms.uAlpha.value = P.opacity; this.mirror.material.uniforms.uAlpha.value = P.opacity;
    this.floorU.uGlow.value = s.rms + beat * 0.5;
    const c = this.camera;
    c.position.set(Math.sin(this.t * 0.05) * 3.2, 3.2 + Math.sin(this.t * 0.07) * 0.5, 15 + Math.sin(this.t * 0.03) * 1.0);
    c.lookAt(0, 2.7, 0);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
