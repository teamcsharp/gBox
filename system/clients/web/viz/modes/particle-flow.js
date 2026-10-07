// 2 Particle Flow: tens of thousands of GPU-animated points forming a flowing, deep waveform.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { NOISE3, PAL_DECL, makeBackdrop, makeFFTTexture } from "../core/glsl.js";
import { Spring, rng } from "../core/util.js";

const MAX = 150000, CLUSTERS = 28, DET = 0.965;

const VS = `${NOISE3}${PAL_DECL}
uniform float uTime, uBass, uMid, uTreble, uBeatAge, uShock, uAspect, uSize, uPR, uIntensity, uMotion;
uniform sampler2D uFFT;
attribute float aRnd;
varying vec3 vCol; varying float vA;
void main(){
  float u = position.x, d = position.y, r1 = position.z;
  float span = 13.0 * max(1.0, uAspect / 1.5);
  float x = u * span;
  float z = 3.0 - d * 22.0;
  float t = uTime;
  float f = texture2D(uFFT, vec2((1.0 - abs(u)) * 0.85 + 0.03, 0.5)).r;
  float w1 = sin(x * 0.32 + t * 0.55 + d * 4.0);
  float w2 = sin(x * 0.11 - t * 0.37 + d * 7.0 + 1.3);
  float n = snoise(vec3(x * 0.1, z * 0.1, t * 0.12));
  float y = -1.6 + ((w1 * 0.45 + w2 * 0.8) * (0.55 + uBass * 0.8) + n * 0.9) * uMotion + f * 2.4 * (1.0 - d * 0.6) * uIntensity;
  float rr = length(vec2(x * 0.55, z + 6.0));
  float ring = uBeatAge * 10.0;
  float sw = exp(-(rr - ring) * (rr - ring) * 0.6) * uShock * exp(-uBeatAge * 1.2);
  y += sw * 1.6;
  vec3 p = vec3(x, y, z);
  p.x += snoise(vec3(x * 0.15 + 5.0, z * 0.15, t * 0.2)) * 0.5 * uMotion;
  p.z += snoise(vec3(x * 0.15, z * 0.15 + 9.0, t * 0.2)) * 0.5 * uMotion;
  p.y += sin(t * 6.0 + r1 * 40.0) * 0.03 * uTreble;
  float a = 1.0;
  float big = 1.0;
  if (aRnd > ${DET}) {
    float cid = floor(r1 * ${CLUSTERS}.0);
    float life = fract(t * 0.06 + cid * 0.137);
    vec3 dir = vec3(snoise(vec3(cid, 1.0, 0.0)), 0.9 + 0.3 * snoise(vec3(cid, 2.0, 0.0)), 0.5 * snoise(vec3(cid, 3.0, 0.0)));
    p += dir * life * life * 7.0;
    p.x += sin(t * 0.7 + cid) * life * 0.6;
    a = smoothstep(0.0, 0.1, life) * (1.0 - smoothstep(0.55, 1.0, life));
    big = 1.6;
  }
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * big * (1.0 + uTreble * 0.8 * step(0.8, aRnd)) * uPR * 12.0 / max(0.5, -mv.z);
  float h = clamp((y + 2.4) * 0.3 + f * 0.6, 0.0, 1.0);
  vec3 col = mix(uC1, uC2, h);
  if (aRnd > 0.86 && aRnd <= ${DET}) col = mix(col, uC3, 0.85);
  col = mix(col, uHi, clamp(f * 0.35 + sw * 0.6, 0.0, 1.0));
  vCol = col;
  vA = a * smoothstep(1.0, 0.65, d) * smoothstep(1.0, 0.88, abs(u)) * (0.4 + 0.6 * h);
}`;
const FS = `varying vec3 vCol; varying float vA;
void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.1, d) * vA; if (a < 0.004) discard; gl_FragColor = vec4(vCol, a); }`;

export default class ParticleFlow extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.position.set(0, 1.0, 8.5);
    this.camera.lookAt(0, -1.2, -4);
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    const r = rng(5), pos = new Float32Array(MAX * 3), rnd = new Float32Array(MAX);
    const cu = [], cd = [];
    for (let c = 0; c < CLUSTERS; c++) { cu.push((r() * 2 - 1) * 0.85); cd.push(0.05 + r() * 0.5); }
    for (let i = 0; i < MAX; i++) {
      const a = r(); rnd[i] = a;
      if (a > DET) {
        const c = (r() * CLUSTERS) | 0;
        pos[i * 3] = cu[c] + (r() - 0.5) * 0.05; pos[i * 3 + 1] = cd[c] + (r() - 0.5) * 0.05; pos[i * 3 + 2] = (c + 0.5) / CLUSTERS;
      } else { pos[i * 3] = r() * 2 - 1; pos[i * 3 + 1] = Math.pow(r(), 0.8); pos[i * 3 + 2] = r(); }
    }
    const g = this.geo = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("aRnd", new THREE.BufferAttribute(rnd, 1));
    this.fft = makeFFTTexture();
    this.u = {
      ...ctx.pal, uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uBeatAge: { value: 9 }, uShock: { value: 0 },
      uAspect: { value: 1.7 }, uSize: { value: 1.3 }, uPR: { value: 1 }, uIntensity: { value: 1 }, uMotion: { value: 1 }, uFFT: { value: this.fft.tex },
    };
    this.points = new THREE.Points(g, new THREE.ShaderMaterial({ uniforms: this.u, vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    this.points.frustumCulled = false;
    this.scene.add(this.points);
    this.bassS = new Spring(10, 5, 0);
  }
  setQuality(q, mult) {
    const n = Math.round(MAX * mult);
    this.geo.setDrawRange(0, n); this.particles = n;
    this.u.uSize.value = 1.0 + (1 - mult) * 0.9; // fewer points -> slightly bigger
  }
  resize(w, h, W, H) { super.resize(w, h); this.u.uAspect.value = w / h; this.u.uPR.value = this.ctx.pr; }
  update(s, dt, rdt) {
    const P = this.params, u = this.u;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    if (hit) { u.uBeatAge.value = 0; u.uShock.value = hit * P.intensity; }
    else u.uBeatAge.value += dt;
    u.uTime.value = this.t;
    u.uBass.value = Math.max(0, this.bassS.step(s.bass * P.intensity, rdt));
    u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uIntensity.value = P.intensity; u.uMotion.value = P.motionAmount;
    this.fft.update(s.fft);
    this.camera.position.x = Math.sin(this.t * 0.04) * 1.2;
    this.camera.lookAt(0, -1.2, -4);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
