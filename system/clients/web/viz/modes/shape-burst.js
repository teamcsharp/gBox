// 10 Shape Burst: hundreds of instanced abstract symbols streaming along invisible curved splines at depth, with trails;
// strong beats trigger SHAPE EXPLOSIONS that disperse nearby symbols and let the stream pull them back.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring, rng } from "../core/util.js";

const MAXB = 900, TR = 4, K = 6, NEXP = 4;

const CURVE = `
vec3 curve(float k, float s, float T){
  float a = s * 6.28318;
  float band = (mod(k, 2.0) < 0.5 ? 1.0 : -1.0) * (2.0 + 0.45 * floor(k / 2.0));
  return vec3((s - 0.5) * uSpanX,
              band + sin(a * 1.3 + k * 1.7 + T * 0.15) * 1.0 + sin(a * 2.7 + k * 0.9) * 0.4,
              -3.0 - k * 1.6 + sin(a * 1.6 + k * 2.3) * 2.5);
}`;
function curveJS(k, s, T, span, out) {
  const a = s * 6.28318, band = (k % 2 < 0.5 ? 1 : -1) * (2.0 + 0.45 * Math.floor(k / 2));
  out.x = (s - 0.5) * span;
  out.y = band + Math.sin(a * 1.3 + k * 1.7 + T * 0.15) * 1.0 + Math.sin(a * 2.7 + k * 0.9) * 0.4;
  out.z = -3.0 - k * 1.6 + Math.sin(a * 1.6 + k * 2.3) * 2.5;
  return out;
}

const VS = `
uniform float uTime, uFlow, uLag, uSpanX, uSpread, uSize, uTreble;
uniform vec4 uExp[${NEXP}];
uniform float uExpS[${NEXP}];
attribute vec4 aA; // curve, s0, speed, shape
attribute vec4 aB; // offY, offZ, size, trail
attribute vec4 aC; // rot0, rotSpeed, colorRand, -
varying vec2 vQ; varying float vShape, vA, vCol, vBoost;
${CURVE}
void main(){
  float trail = aB.w;
  float s = fract(aA.y + uFlow * aA.z - trail * uLag);
  vec3 p = curve(aA.x, s, uTime) + vec3(0.0, aB.x, aB.y) * uSpread;
  float spin = 0.0, boost = 0.0;
  for (int i = 0; i < ${NEXP}; i++){
    float age = uExp[i].w;
    if (age < 0.0 || age > 6.0) continue;
    vec3 d = p - uExp[i].xyz;
    float dist2 = dot(d, d);
    float infl = exp(-dist2 / 12.0);
    vec3 dir = normalize(d + vec3(aC.z - 0.5, aB.x, aB.y) * 0.6 + 1e-3);
    float f = uExpS[i] * age * exp(-age * 1.6) * 16.0;
    p += dir * infl * f;
    spin += infl * f * 1.5;
    boost += infl * exp(-age * 1.2) * uExpS[i];
  }
  float fade = smoothstep(0.0, 0.06, s) * smoothstep(1.0, 0.94, s);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  float ang = aC.x + uTime * aC.y + spin;
  vec2 cs = vec2(cos(ang), sin(ang));
  vec2 q = position.xy;
  float sz = aB.z * uSize * (1.0 - trail * 0.16) * (1.0 + uTreble * 0.25 + boost * 0.8);
  mv.xy += vec2(q.x * cs.x - q.y * cs.y, q.x * cs.y + q.y * cs.x) * sz;
  gl_Position = projectionMatrix * mv;
  vQ = q * 2.0; vShape = aA.w; vCol = aC.z; vBoost = boost;
  vA = fade * (trail < 0.5 ? 1.0 : pow(1.0 - trail / ${TR}.0, 2.0) * 0.45);
}`;
const FS = `${PAL_DECL}
uniform float uGain;
varying vec2 vQ; varying float vShape, vA, vCol, vBoost;
float sdBox(vec2 p, vec2 b){ vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
float sdTri(vec2 p, float r){
  const float k = 1.7320508; p.x = abs(p.x) - r; p.y = p.y + r / k;
  if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0;
  p.x -= clamp(p.x, -2.0 * r, 0.0); return -length(p) * sign(p.y);
}
float sdStar5(vec2 p, float r, float rf){
  const vec2 k1 = vec2(0.809016994375, -0.587785252292);
  const vec2 k2 = vec2(-0.809016994375, -0.587785252292);
  p.x = abs(p.x);
  p -= 2.0 * max(dot(k1, p), 0.0) * k1;
  p -= 2.0 * max(dot(k2, p), 0.0) * k2;
  p.x = abs(p.x);
  p.y -= r;
  vec2 ba = rf * vec2(-k1.y, k1.x) - vec2(0.0, 1.0);
  float h = clamp(dot(p, ba) / dot(ba, ba), 0.0, r);
  return length(p - ba * h) * sign(p.y * ba.x - p.x * ba.y);
}
float shape(vec2 q, float id){
  if (id < 0.5) return length(q) - 0.55;                                   // disc
  if (id < 1.5) return abs(length(q) - 0.55) - 0.09;                      // ring
  if (id < 2.5) { vec2 r = vec2(q.x + q.y, q.x - q.y) * 0.70710678;       // slanted cross
                  return min(sdBox(r, vec2(0.62, 0.1)), sdBox(r, vec2(0.1, 0.62))); }
  if (id < 3.5) return abs(sdTri(q * vec2(1.0, -1.0), 0.6)) - 0.07;       // inverted triangle outline
  if (id < 4.5) return (abs(q.x) * 1.4 + abs(q.y) - 0.75) * 0.58;         // tall diamond
  if (id < 5.5) return abs(sdBox(q, vec2(0.36, 0.5))) - 0.07;             // upright rectangle outline
  if (id < 6.5) return sdStar5(q, 0.68, 0.45);                           // star
  return min(abs(length(q) - 0.6) - 0.06, length(q) - 0.17);             // orbit glyph
}
void main(){
  float d = shape(vQ, vShape);
  float aa = fwidth(d) * 1.2;
  float fill = 1.0 - smoothstep(-aa, aa, d);
  float glow = exp(-max(d, 0.0) * 7.0) * 0.35;
  vec3 c = vCol < 0.45 ? uC2 : vCol < 0.8 ? uC1 : vCol < 0.93 ? uC3 : uHi;
  c = mix(c, uHi, clamp(fill * 0.25 + vBoost * 0.6, 0.0, 1.0));
  float a = (fill + glow) * vA * uGain * (1.0 + vBoost);
  if (a < 0.003) discard;
  gl_FragColor = vec4(c, a);
}`;

export default class ShapeBurst extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.position.set(0, 0, 10);
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    const plane = new THREE.PlaneGeometry(1, 1);
    const g = this.geo = new THREE.InstancedBufferGeometry();
    g.index = plane.index; g.setAttribute("position", plane.getAttribute("position"));
    const n = MAXB * TR, A = new Float32Array(n * 4), B = new Float32Array(n * 4), C = new Float32Array(n * 4);
    const r = rng(77);
    for (let j = 0; j < MAXB; j++) {
      const k = (r() * K) | 0, s0 = r(), sp = 0.7 + r() * 0.6, shp = (r() * 8) | 0;
      const ang = r() * Math.PI * 2, rad = Math.sqrt(r()), oy = Math.cos(ang) * rad, oz = Math.sin(ang) * rad;
      const size = 0.16 + Math.pow(r(), 3) * 0.42, r0 = r() * 6, rs = (r() - 0.5) * 2, cr = r();
      for (let t = 0; t < TR; t++) {
        const i = (j * TR + t) * 4;
        A[i] = k; A[i + 1] = s0; A[i + 2] = sp; A[i + 3] = shp;
        B[i] = oy; B[i + 1] = oz; B[i + 2] = size; B[i + 3] = t;
        C[i] = r0; C[i + 1] = rs; C[i + 2] = cr;
      }
    }
    g.setAttribute("aA", new THREE.InstancedBufferAttribute(A, 4)); g.setAttribute("aB", new THREE.InstancedBufferAttribute(B, 4)); g.setAttribute("aC", new THREE.InstancedBufferAttribute(C, 4));
    this.exp = []; for (let i = 0; i < NEXP; i++) this.exp.push(new THREE.Vector4(0, 0, 0, -1));
    this.expS = new Float32Array(NEXP);
    this.u = { ...ctx.pal, uTime: { value: 0 }, uFlow: { value: 0 }, uLag: { value: 0.004 }, uSpanX: { value: 34 }, uSpread: { value: 0.9 }, uSize: { value: 1 },
      uTreble: { value: 0 }, uExp: { value: this.exp }, uExpS: { value: this.expS }, uGain: { value: 1 } };
    const m = new THREE.ShaderMaterial({ uniforms: this.u, vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    m.extensions.derivatives = true;
    this.mesh = new THREE.Mesh(g, m); this.mesh.frustumCulled = false; this.scene.add(this.mesh);
    this.flow = 0; this.vel = new Spring(5, 3.5, 0.02); this.cool = 0.8; this.ei = 0; this.tmp = { x: 0, y: 0, z: 0 };
  }
  setQuality(q, mult) { const n = Math.round(250 + 650 * mult); this.geo.instanceCount = n * TR; this.particles = n; }
  resize(w, h) {
    super.resize(w, h);
    const th = Math.tan((this.camera.fov * Math.PI) / 360);
    this.u.uSpanX.value = 2 * th * 22 * (w / h) * 1.15; // wide enough at the farthest curve
  }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    if (hit) this.vel.kick(hit * 0.05 * P.intensity);
    const v = Math.max(0.006, this.vel.step((0.018 + s.rms * 0.03) * P.motionAmount, rdt));
    this.flow += v * dt;
    const u = this.u;
    u.uTime.value = this.t; u.uFlow.value = this.flow; u.uLag.value = 0.002 + v * 0.12; u.uTreble.value = s.treble;
    u.uSpread.value = 0.8 + s.mid * 0.5; u.uGain.value = (0.85 + s.rms * 0.3) * P.opacity;
    for (let i = 0; i < NEXP; i++) if (this.exp[i].w >= 0) { this.exp[i].w += dt; if (this.exp[i].w > 6) this.exp[i].w = -1; }
    // occasional SHAPE EXPLOSIONS on strong beats
    this.cool -= rdt;
    if (hit > 0.6 && this.cool < 0 && (hit > 0.85 || Math.random() < 0.45)) {
      const k = (Math.random() * K) | 0, sc = 0.25 + Math.random() * 0.5;
      const c = curveJS(k, sc, this.t, u.uSpanX.value, this.tmp);
      const e = this.exp[this.ei]; e.set(c.x, c.y, c.z, 0); this.expS[this.ei] = (0.7 + hit * 0.6) * P.intensity;
      this.ei = (this.ei + 1) % NEXP; this.cool = 1.4 + Math.random() * 1.5;
    }
    this.camera.position.x = Math.sin(this.t * 0.05) * 0.8; this.camera.position.y = Math.sin(this.t * 0.04) * 0.4;
    this.camera.lookAt(0, 0, -4);
    this.bg.material.uniforms.uTime.value = this.t;
  }
}
