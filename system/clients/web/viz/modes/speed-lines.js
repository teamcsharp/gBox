// 5 Speed Lines: curved luminous streaks rushing out of a wandering vanishing point (anime / hyperspace).
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { HASH, PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring, rng, noise2 } from "../core/util.js";

const MAX = 1000, SEG = 12;

const VS = `
uniform float uTravel, uLen, uAspect, uWarp, uWidth;
uniform vec2 uVP;
attribute vec4 aA; // angle, seed, speed, curvature
attribute vec4 aB; // width, brightness, length, hue
varying float vS, vSide, vBright, vHue;
void main(){
  float ph = fract(aA.y + uTravel * aA.z);
  float R = length(vec2(uAspect, 1.0)) * 1.25;
  float r = pow(ph, 2.0) * R;
  float len = (0.12 + uLen * aB.z) * (0.3 + r);
  float s = position.x;
  float rs = max(r - len * s, 0.0);
  float a = aA.x + aA.w * rs * rs * 0.35 + uWarp * rs * 0.25;
  vec2 dir = vec2(cos(a), sin(a));
  vec2 p = uVP * (1.0 - smoothstep(0.0, 1.6, rs)) + dir * rs;
  vec2 nrm = vec2(-dir.y, dir.x);
  float w = aB.x * uWidth * (0.12 + rs) * (1.0 - s * 0.85);
  p += nrm * position.y * w;
  vS = s; vSide = position.y;
  vBright = aB.y * smoothstep(0.08, 0.45, rs) * (1.0 - smoothstep(0.88, 1.0, ph));
  vHue = aB.w;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 0.0, 1.0);
}`;
const FS = `${PAL_DECL} uniform float uGain; varying float vS, vSide, vBright, vHue;
void main(){
  float core = pow(clamp(1.0 - abs(vSide), 0.0, 1.0), 2.0);
  float tail = pow(clamp(1.0 - vS, 0.0, 1.0), 1.6);
  vec3 c = vHue < 0.55 ? uC2 : vHue < 0.85 ? uC1 : uC3;
  if (vHue > 0.93) c = uHi;
  c = mix(c, uHi, core * core * 0.7);
  gl_FragColor = vec4(c * 1.6, min(1.0, core * tail * vBright * uGain * 1.6));
}`;
const BG_FS = `${PAL_DECL} uniform float uTime, uAspect, uStep, uGlow; uniform vec2 uVP; varying vec2 vUv; ${HASH}
void main(){
  vec2 p = (vUv - 0.5) * 2.0 * vec2(uAspect, 1.0);
  vec2 q = p - uVP;
  float r = length(q);
  vec3 c = mix(uBg1 * 0.9, uBg0, smoothstep(0.0, 1.6, r));
  c += mix(uC2, uHi, 0.3) * exp(-r * 7.0) * (0.06 + uGlow * 0.12);
  // manga focus lines, stepped at 12 fps
  float ang = atan(q.y, q.x);
  float n = hash12(vec2(floor(ang * 160.0), floor(uStep * 12.0)));
  float lines = step(0.82, n) * smoothstep(0.5, 1.5, r) * smoothstep(0.5, 0.0, abs(fract(ang * 160.0) - 0.5) * 2.0 - 0.3);
  c += mix(uC1, uHi, 0.3) * lines * 0.06;
  c *= 1.0 - 0.35 * smoothstep(0.9, 2.2, r);
  gl_FragColor = vec4(c, 1.0);
}`;

export default class SpeedLines extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1, 1);
    this.bgU = { uStep: { value: 0 }, uGlow: { value: 0 }, uVP: { value: new THREE.Vector2() } };
    this.scene.add(this.bg = makeBackdrop(ctx.pal, this.bgU, BG_FS));
    const base = new THREE.PlaneGeometry(1, 2, SEG, 1); base.translate(0.5, 0, 0); // x in [0,1] along streak, y in [-1,1] across
    const g = this.geo = new THREE.InstancedBufferGeometry();
    g.index = base.index; g.setAttribute("position", base.getAttribute("position"));
    const r = rng(9), A = new Float32Array(MAX * 4), B = new Float32Array(MAX * 4);
    for (let i = 0; i < MAX; i++) {
      A[i * 4] = r() * Math.PI * 2; A[i * 4 + 1] = r(); A[i * 4 + 2] = 0.6 + r() * 0.9; A[i * 4 + 3] = (r() - 0.5) * 0.3;
      const bold = r() < 0.06;
      B[i * 4] = bold ? 1.5 + r() * 0.8 : 0.4 + r() * 0.9; B[i * 4 + 1] = bold ? 1.0 : 0.35 + r() * 0.65; B[i * 4 + 2] = 0.5 + r(); B[i * 4 + 3] = bold ? 0.97 : r() * 0.93;
    }
    g.setAttribute("aA", new THREE.InstancedBufferAttribute(A, 4)); g.setAttribute("aB", new THREE.InstancedBufferAttribute(B, 4));
    this.u = { ...ctx.pal, uTravel: { value: 0 }, uLen: { value: 0.1 }, uAspect: { value: 1.7 }, uWarp: { value: 0 }, uWidth: { value: 0.006 }, uVP: this.bgU.uVP, uGain: { value: 1 } };
    this.mesh = new THREE.Mesh(g, new THREE.ShaderMaterial({ uniforms: this.u, vertexShader: VS, fragmentShader: FS, transparent: true, side: THREE.DoubleSide, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending }));
    this.mesh.frustumCulled = false; this.scene.add(this.mesh);
    this.vel = new Spring(5, 3.2, 0.05); this.travel = 0; this.vpx = new Spring(3, 2.5, 0); this.vpy = new Spring(3, 2.5, 0);
  }
  setQuality(q, mult) { this.geo.instanceCount = Math.round(250 + 750 * mult); this.particles = this.geo.instanceCount; }
  resize(w, h) {
    const a = w / h, c = this.camera;
    c.left = -a; c.right = a; c.top = 1; c.bottom = -1; c.updateProjectionMatrix();
    this.u.uAspect.value = a; this.bg.material.uniforms.uAspect.value = a;
    this.u.uWidth.value = 0.0045 * Math.max(0.6, 900 / Math.max(300, h)) ** 0.3;
  }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    if (hit) this.vel.kick(hit * 2.2 * P.intensity);
    // rms = velocity; near-suspended at silence (but never frozen)
    const v = Math.max(0.015, this.vel.step(0.025 + (s.rms * 0.45 + s.bass * 0.2) * P.intensity, rdt));
    this.travel += v * dt * P.motionAmount;
    this.u.uTravel.value = this.travel;
    this.u.uLen.value = 0.04 + Math.min(1.6, v * 1.3);
    this.u.uWarp.value = Math.sin(this.t * 0.11) * 0.25 + s.mid * 0.15;
    this.u.uGain.value = (0.75 + Math.min(0.6, v)) * P.opacity;
    const vp = this.bgU.uVP.value;
    vp.set(this.vpx.step(noise2(this.t * 0.07, 3.1) * 0.45, rdt), this.vpy.step(noise2(4.7, this.t * 0.06) * 0.22, rdt));
    this.bgU.uStep.value = Math.floor(this.t * 12) / 12; this.bgU.uGlow.value = Math.min(1, v * 2);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
