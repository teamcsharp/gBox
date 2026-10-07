// 8 Liquid Glass: a thick deforming glass ribbon (vertex-shader sweep, analytic-ish normals), Fresnel, procedural
// environment reflection, fake screen-space refraction of the backdrop with chromatic aberration, internal glow; + glass bubbles.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { HASH, NOISE3, PAL_DECL, makeBackdrop, FS_VERT } from "../core/glsl.js";
import { Spring, rng } from "../core/util.js";

const SU = 360, SV = 28, BMAX = 30;

// backdrop used both for drawing and for the refraction lookups
const BGF = `
vec3 glassBg(vec2 uv, float t){
  vec3 c = mix(uBg0, uBg1, smoothstep(1.1, 0.0, length((uv - vec2(0.5, 0.42)) * vec2(1.3, 1.0))));
  for (int i = 0; i < 4; i++){
    float fi = float(i);
    vec2 cpos = vec2(0.5 + 0.38 * sin(t * 0.05 * (1.0 + fi * 0.3) + fi * 2.1), 0.5 + 0.3 * cos(t * 0.04 * (1.0 + fi * 0.2) + fi * 1.3));
    float b = exp(-dot(uv - cpos, uv - cpos) * 9.0);
    c += (i == 1 ? uC3 : i == 2 ? uC2 : uC1) * b * 0.22;
  }
  // faint diagonal light bands (studio feel), refracted they read as caustics
  c += uC2 * smoothstep(0.92, 1.0, sin((uv.x + uv.y * 0.6) * 18.0 + t * 0.1)) * 0.05;
  return c;
}`;
const BG_FS = `${PAL_DECL} uniform float uTime; varying vec2 vUv; ${BGF} void main(){ gl_FragColor = vec4(glassBg(vUv, uTime), 1.0); }`;

const RIB_VS = `${NOISE3}
uniform float uTime, uAmp, uBass, uMid, uSpan, uThick;
varying vec3 vN, vW; varying float vU;
vec3 center(float u){
  float x = (u - 0.5) * uSpan, t = uTime;
  return vec3(x, -1.45 + sin(x * 0.22 + t * 0.4) * 0.8 * uAmp + snoise(vec3(x * 0.09, t * 0.1, 0.0)) * 0.7 * uAmp, sin(x * 0.15 - t * 0.3) * 1.6 - 1.0);
}
vec3 surf(float u, float th){
  vec3 c = center(u);
  vec3 T = normalize(center(u + 0.002) - c);
  vec3 N1 = normalize(cross(vec3(0.0, 0.0, 1.0), T));
  vec3 B = cross(T, N1);
  float x = (u - 0.5) * uSpan;
  float tw = x * 0.18 + uTime * 0.35 + uBass * 0.8;
  vec3 e1 = cos(tw) * N1 + sin(tw) * B, e2 = -sin(tw) * N1 + cos(tw) * B;
  float bulge = 1.0 + 0.35 * snoise(vec3(x * 0.3, uTime * 0.25, 4.0)) + uMid * 0.4;
  float taper = smoothstep(0.0, 0.06, u) * smoothstep(1.0, 0.94, u);
  return c + (e1 * cos(th) * 1.05 + e2 * sin(th) * uThick * bulge) * (0.35 + 0.65 * taper);
}
void main(){
  float u = position.x, th = position.y;
  vec3 p = surf(u, th);
  vec3 du = surf(u + 0.0015, th) - p, dv = surf(u, th + 0.05) - p;
  vec3 n = normalize(cross(du, dv));
  if (dot(n, p - center(u)) < 0.0) n = -n;
  vec4 w = modelMatrix * vec4(p, 1.0);
  vW = w.xyz; vN = normalize(mat3(modelMatrix) * n); vU = u;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const BUB_VS = `
varying vec3 vN, vW; varying float vU;
void main(){
  mat4 m = modelMatrix * instanceMatrix;
  vec4 w = m * vec4(position, 1.0);
  vW = w.xyz; vN = normalize(mat3(m) * normal); vU = 0.5;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;
const GLASS_FS = `${PAL_DECL}
uniform float uTime, uGlow, uBubble, uAlpha; uniform vec2 uRes;
varying vec3 vN, vW; varying float vU;
${BGF}
vec3 env(vec3 r){
  vec3 c = mix(uBg0, mix(uC1, uBg1, 0.5), smoothstep(-0.6, 0.9, r.y));
  float az = atan(r.z, r.x);
  c += uHi * smoothstep(0.93, 0.995, sin(az * 3.0 + 0.8)) * smoothstep(-0.1, 0.5, r.y) * 1.1;
  c += uC2 * pow(max(0.0, r.y), 6.0) * 0.8;
  c += uC3 * smoothstep(0.6, 1.0, -r.y) * 0.3;
  return c;
}
void main(){
  vec3 N = normalize(vN);
  vec3 V = normalize(cameraPosition - vW);
  if (dot(N, V) < 0.0) N = -N;
  float ndv = clamp(dot(N, V), 0.0, 1.0);
  float fres = 0.06 + 0.94 * pow(1.0 - ndv, 4.0);
  vec3 refl = env(reflect(-V, N));
  vec2 uv = gl_FragCoord.xy / uRes;
  vec3 vn = (viewMatrix * vec4(N, 0.0)).xyz;
  float str = mix(0.07, -0.12, uBubble);
  vec2 off = vn.xy * str;
  vec3 refr = vec3(glassBg(uv - off, uTime).r, glassBg(uv - off * 1.1, uTime).g, glassBg(uv - off * 1.22, uTime).b);
  refr *= mix(vec3(1.0), mix(uC2, uHi, 0.5), 0.35);
  vec3 L = normalize(vec3(0.4, 0.8, 0.5));
  float spec = pow(max(dot(reflect(-L, N), V), 0.0), 80.0) * 1.4;
  float glow = (1.0 - ndv) * (0.12 + uGlow * 0.5) * (0.6 + 0.4 * sin(vU * 30.0 - uTime * 2.0));
  vec3 col = mix(refr * 1.1, refl, fres) + uHi * spec + uC2 * glow;
  if (uBubble > 0.5) {
    vec3 film = 0.5 + 0.5 * cos(6.2831 * (fres * 1.6 + vec3(0.0, 0.33, 0.67)) + uTime * 0.2);
    col += film * fres * 0.35;
    gl_FragColor = vec4(col, (0.25 + fres * 0.75) * uAlpha);
  } else gl_FragColor = vec4(col, uAlpha);
}`;

export default class LiquidGlass extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.fov = 45; this.camera.position.set(0, 0.3, 11);
    this.scene.add(this.bg = makeBackdrop(ctx.pal, {}, BG_FS));
    // ribbon grid: position = (u, theta, 0)
    const pos = new Float32Array((SU + 1) * (SV + 1) * 3), idx = [];
    for (let i = 0; i <= SU; i++) for (let j = 0; j <= SV; j++) { const k = (i * (SV + 1) + j) * 3; pos[k] = i / SU; pos[k + 1] = (j / SV) * Math.PI * 2; }
    for (let i = 0; i < SU; i++) for (let j = 0; j < SV; j++) { const a = i * (SV + 1) + j, b = a + SV + 1; idx.push(a, b, a + 1, b, b + 1, a + 1); }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setIndex(idx);
    this.res = new THREE.Vector2(1, 1);
    this.ribU = { ...ctx.pal, uTime: { value: 0 }, uAmp: { value: 1 }, uBass: { value: 0 }, uMid: { value: 0 }, uSpan: { value: 30 }, uThick: { value: 0.3 },
      uGlow: { value: 0 }, uBubble: { value: 0 }, uAlpha: { value: 1 }, uRes: { value: this.res } };
    this.rib = new THREE.Mesh(g, new THREE.ShaderMaterial({ uniforms: this.ribU, vertexShader: RIB_VS, fragmentShader: GLASS_FS, side: THREE.DoubleSide }));
    this.rib.frustumCulled = false; this.scene.add(this.rib);
    // bubbles
    this.bubU = { ...ctx.pal, uTime: this.ribU.uTime, uGlow: this.ribU.uGlow, uBubble: { value: 1 }, uAlpha: { value: 1 }, uRes: { value: this.res } };
    this.bub = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 32, 20), new THREE.ShaderMaterial({ uniforms: this.bubU, vertexShader: BUB_VS, fragmentShader: GLASS_FS, transparent: true, depthWrite: false }), BMAX);
    this.bub.frustumCulled = false; this.scene.add(this.bub);
    const r = rng(3);
    this.bs = [];
    for (let i = 0; i < BMAX; i++) {
      const side = i % 2 ? 1 : -1;
      this.bs.push({ x: side * (2.8 + r() * 7), y: -5 + r() * 10, z: -4 + r() * 5, rad: 0.15 + Math.pow(r(), 2) * 0.55, sp: 0.15 + r() * 0.35, ph: r() * 10, pulse: new Spring(50, 6, 0) });
    }
    this.dummy = new THREE.Object3D();
    this.amp = new Spring(5, 3.5, 1); this.N = 20;
  }
  setQuality(q, mult) { this.N = Math.round(10 + 20 * mult); this.bub.count = this.N; this.particles = this.N; }
  resize(w, h, W, H) {
    super.resize(w, h); this.res.set(W, H);
    const th = Math.tan((this.camera.fov * Math.PI) / 360);
    this.ribU.uSpan.value = 2 * th * 12 * (w / h) * 1.25 + 4;
    this.aspect = w / h;
  }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    const u = this.ribU;
    u.uTime.value = this.t;
    u.uAmp.value = this.amp.step((0.8 + s.bass * 0.7 * P.intensity) * P.motionAmount, rdt);
    u.uBass.value = s.bass; u.uMid.value = s.mid; u.uThick.value = 0.28 + s.rms * 0.12;
    u.uGlow.value = s.rms * 0.6 + s.beat * 0.6 + s.speechActivity * 0.2;
    const d = this.dummy, top = 6, a = this.aspect || 1.7;
    for (let i = 0; i < this.N; i++) {
      const b = this.bs[i];
      if (hit) b.pulse.kick(hit * 2.5);
      b.y += dt * b.sp * (1 + s.rms);
      if (b.y > top) b.y = -top;
      const x = b.x * Math.min(1.4, a / 1.7) + Math.sin(this.t * 0.4 + b.ph) * 0.3;
      d.position.set(x, b.y, b.z);
      d.scale.setScalar(b.rad * (1 + b.pulse.step(0, rdt) * 0.15 + s.treble * 0.08));
      d.updateMatrix(); this.bub.setMatrixAt(i, d.matrix);
    }
    this.bub.instanceMatrix.needsUpdate = true;
    this.camera.position.x = Math.sin(this.t * 0.05) * 0.8;
    this.camera.lookAt(0, -0.4, 0);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
