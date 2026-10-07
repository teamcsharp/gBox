// 1 Smooth Wave: translucent silk ribbons drifting past both edges (PS3-menu feel).
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { NOISE3, PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring, rng } from "../core/util.js";

const VS = `${NOISE3}
uniform float uTime, uAmp, uBass, uMid, uTreble, uSeed, uY, uWidth, uSpan, uPhase;
varying float vAcross, vU, vTw;
void main(){
  float x = (uv.x - 0.5) * uSpan;
  float t = uTime + uPhase;
  float v = uv.y - 0.5;
  float y = uY
    + sin(x * 0.16 + t * 0.33 + uSeed) * 0.55 * uAmp
    + sin(x * 0.071 - t * 0.19 + uSeed * 2.1) * 0.85 * uAmp
    + snoise(vec3(x * 0.05, t * 0.07, uSeed)) * (0.45 + uBass * 1.1);
  float tw = sin(x * 0.12 + t * 0.25 + uSeed * 3.0) + 0.6 * snoise(vec3(x * 0.08 + 11.0, t * 0.09, uSeed));
  float a = tw * 1.35;
  float w = uWidth * (0.75 + 0.25 * sin(x * 0.2 + t * 0.3 + uSeed)) * (1.0 + uMid * 0.5);
  float z = sin(x * 0.08 + t * 0.17 + uSeed) * 1.2;
  vec3 p = vec3(x, y, z) + vec3(0.0, cos(a), sin(a)) * v * w;
  p.y += sin(x * 1.1 + t * 2.4 + v * 6.0) * 0.025 * uTreble;
  vAcross = v * 2.0; vU = uv.x; vTw = cos(a);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const FS = `${PAL_DECL}
uniform float uAlpha, uGlow, uHue;
varying float vAcross, vU, vTw;
void main(){
  float a = abs(vAcross);
  float edge = smoothstep(0.86, 0.975, a) * (1.0 - smoothstep(0.975, 1.0, a));
  float body = 1.0 - smoothstep(0.1, 1.0, a);
  float graze = clamp(1.0 - abs(vTw), 0.0, 1.0);
  float ends = smoothstep(0.0, 0.1, vU) * smoothstep(1.0, 0.9, vU);
  vec3 base = mix(uC1, uC2, clamp(uHue + 0.35 * vTw, 0.0, 1.0));
  vec3 col = base * (0.45 + 0.55 * body) + uHi * (edge * 0.7 + pow(graze, 5.0) * 0.5) * (0.7 + uGlow);
  float alpha = (body * 0.11 + edge * 0.5 + pow(graze, 4.0) * 0.22) * uAlpha * ends;
  gl_FragColor = vec4(col, alpha);
}`;
const DUST_VS = `
uniform float uTime, uPR, uTreble;
attribute float aSeed;
varying float vA;
void main(){
  vec3 p = position;
  p.x += mod(uTime * (0.15 + aSeed * 0.3) + aSeed * 50.0, 40.0) - 20.0;
  p.y += sin(uTime * 0.3 + aSeed * 30.0) * 0.3;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  float tw = 0.5 + 0.5 * sin(uTime * (1.5 + aSeed * 3.0) + aSeed * 90.0);
  vA = tw * (0.25 + uTreble * 0.75);
  gl_PointSize = (1.5 + aSeed * 2.5) * uPR * 8.0 / -mv.z;
}`;
const DUST_FS = `${PAL_DECL} varying float vA;
void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * vA; gl_FragColor = vec4(mix(uC2, uHi, 0.6), a); }`;

const NMAX = 8;

export default class SmoothWave extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.fov = 48; this.camera.position.set(0, 0.2, 10);
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    this.shared = { uTime: { value: 0 }, uAmp: { value: 1 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uGlow: { value: 0 } };
    const geo = new THREE.PlaneGeometry(1, 1, 260, 24);
    const r = rng(11);
    this.ribbons = [];
    for (let i = 0; i < NMAX; i++) {
      const u = {
        ...ctx.pal, ...this.shared,
        uSeed: { value: i * 1.37 + 0.4 }, uY: { value: -2.5 + (i % 3) * 0.5 + r() * 0.3 }, uWidth: { value: 0.6 + r() * 1.1 },
        uSpan: { value: 40 }, uPhase: { value: r() * 20 }, uHue: { value: i / (NMAX - 1) }, uAlpha: { value: 0.75 + r() * 0.4 },
      };
      const mat = new THREE.ShaderMaterial({ uniforms: u, vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.frustumCulled = false;
      mesh.position.z = -7 + i * 1.15;
      this.scene.add(mesh); this.ribbons.push(mesh);
    }
    // dust
    const N = 500, pos = new Float32Array(N * 3), seed = new Float32Array(N);
    for (let i = 0; i < N; i++) { pos[i * 3] = 0; pos[i * 3 + 1] = (r() - 0.5) * 9; pos[i * 3 + 2] = -8 + r() * 12; seed[i] = r(); }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute("position", new THREE.BufferAttribute(pos, 3)); dg.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    this.dustU = { ...ctx.pal, uTime: this.shared.uTime, uPR: { value: 1 }, uTreble: this.shared.uTreble };
    this.dust = new THREE.Points(dg, new THREE.ShaderMaterial({ uniforms: this.dustU, vertexShader: DUST_VS, fragmentShader: DUST_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    this.dust.frustumCulled = false; this.scene.add(this.dust);
    this.amp = new Spring(6, 4, 1); this.glow = new Spring(40, 9, 0);
    this.particles = N;
  }
  setQuality(q, mult) {
    const n = Math.round(4 + 4 * mult);
    this.ribbons.forEach((m, i) => (m.visible = i < n));
  }
  resize(w, h, W, H) {
    super.resize(w, h);
    const th = Math.tan((this.camera.fov * Math.PI) / 360);
    for (const m of this.ribbons) m.material.uniforms.uSpan.value = 2 * th * (this.camera.position.z - m.position.z) * (w / h) * 1.2 + 6;
    this.dustU.uPR.value = this.ctx.pr;
  }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s);
    if (hit) this.glow.kick(hit * 6);
    const u = this.shared;
    u.uTime.value = this.t;
    u.uAmp.value = this.amp.step((0.7 + s.bass * 0.8 * P.intensity + s.rms * 0.3) * P.motionAmount, rdt);
    u.uBass.value = s.bass * P.intensity; u.uMid.value = s.mid; u.uTreble.value = s.treble;
    u.uGlow.value = Math.max(0, this.glow.step(0, rdt)) + s.rms * 0.3;
    for (const m of this.ribbons) m.material.uniforms.uAlpha.value = (0.7 + 0.35 * Math.sin(m.material.uniforms.uSeed.value * 4.1)) * P.opacity;
    this.camera.position.x = Math.sin(this.t * 0.05) * 0.6;
    this.camera.position.y = 0.2 + Math.sin(this.t * 0.07) * 0.2;
    this.camera.lookAt(0, -0.4, 0);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
