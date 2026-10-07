// 9 Retro Grid: endless wireframe terrain scrolling toward a horizon with a big glowing striped orb
// (orb size/brightness = station energy), fog, stars, cyan/violet lines.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { HASH, NOISE3, PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring } from "../core/util.js";

const DEPTH = 140, CELL = 2.0;

const TER_VS = `${NOISE3}
uniform float uScroll, uBass, uAmp;
varying vec3 vW; varying float vH;
float height(vec2 q){
  float side = smoothstep(2.5, 14.0, abs(q.x));
  float n = snoise(vec3(q.x * 0.06, q.y * 0.06, 0.0)) * 0.5 + 0.5;
  float n2 = snoise(vec3(q.x * 0.17, q.y * 0.17, 3.0)) * 0.5 + 0.5;
  return side * (n * 7.0 + n2 * 2.0) * uAmp + side * uBass * 1.5 * n2;
}
void main(){
  vec3 p = position;
  vec2 q = vec2(p.x, p.z - uScroll);
  p.y = height(q);
  vH = p.y; vW = p;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const TER_FS = `${PAL_DECL}
uniform float uScroll, uLine, uFlash;
varying vec3 vW; varying float vH;
void main(){
  vec2 g = vec2(vW.x, vW.z - uScroll) / ${CELL.toFixed(1)};
  vec2 fw = fwidth(g);
  vec2 gd = abs(fract(g - 0.5) - 0.5) / max(fw, 1e-4);
  float line = 1.0 - min(min(gd.x, gd.y) / 1.2, 1.0);
  float dist = -vW.z;
  vec3 lc = mix(uC2, uC3, smoothstep(0.5, 7.0, vH));
  vec3 fill = mix(uBg0, uC3 * 0.25, smoothstep(0.0, 8.0, vH)) * 0.5;
  vec3 c = fill + lc * line * (uLine + uFlash) ;
  float fog = smoothstep(${(DEPTH * 0.25).toFixed(1)}, ${(DEPTH * 0.95).toFixed(1)}, dist);
  vec3 horizon = mix(uC3, uBg1, 0.45) * 0.55;
  gl_FragColor = vec4(mix(c, horizon, fog), 1.0);
}`;
const SKY_FS = `${PAL_DECL} uniform float uTime, uAspect, uHorizon; varying vec2 vUv; ${HASH}
void main(){
  float y = vUv.y - uHorizon;
  vec3 c = mix(mix(uC3, uBg1, 0.45) * 0.55, uBg0, smoothstep(0.0, 0.55, y));
  vec2 p = vUv * vec2(uAspect, 1.0) * 90.0;
  float h = hash12(floor(p));
  float tw = 0.5 + 0.5 * sin(uTime * (1.0 + h * 3.0) + h * 50.0);
  c += uHi * step(0.992, h) * smoothstep(0.4, 0.1, length(fract(p) - 0.5)) * tw * smoothstep(0.05, 0.3, y) * 0.8;
  gl_FragColor = vec4(c, 1.0);
}`;
const ORB_VS = `varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const ORB_FS = `${PAL_DECL} uniform float uTime, uBright;
varying vec2 vP;
void main(){
  float r = length(vP);           // disk radius 1, quad extends to 2.2 for the halo
  float y = vP.y;
  vec3 top = mix(uC2, uHi, 0.3), bot = uC3;
  vec3 c = mix(bot, top, smoothstep(-0.9, 0.9, y));
  // stripes: gaps widen toward the bottom, scrolling down
  float s = fract(y * 9.0 + uTime * 0.25);
  float gap = clamp((0.55 - y) * 0.42, 0.0, 0.6);
  float stripe = y < 0.55 ? step(gap, s) : 1.0;
  float disk = smoothstep(1.0, 0.985, r) * stripe;
  float halo = exp(-max(r - 1.0, 0.0) * 3.2) * (1.0 - disk) * 0.55;
  vec3 col = c * disk * (0.45 + uBright * 0.45) + mix(uC3, uC2, 0.3) * halo * uBright;
  gl_FragColor = vec4(col, max(disk, halo * uBright));
}`;

export default class RetroGrid extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.fov = 60; this.camera.far = 400;
    this.skyU = { uHorizon: { value: 0.45 } };
    this.scene.add(this.bg = makeBackdrop(ctx.pal, this.skyU, SKY_FS));
    // terrain
    const W = 120, segX = 90, segZ = 110;
    const g = new THREE.PlaneGeometry(W, DEPTH, segX, segZ);
    g.rotateX(-Math.PI / 2); g.translate(0, 0, -DEPTH / 2 + 8);
    this.terU = { ...ctx.pal, uScroll: { value: 0 }, uBass: { value: 0 }, uAmp: { value: 1 }, uLine: { value: 1 }, uFlash: { value: 0 } };
    const tm = new THREE.ShaderMaterial({ uniforms: this.terU, vertexShader: TER_VS, fragmentShader: TER_FS });
    tm.extensions.derivatives = true;
    this.ter = new THREE.Mesh(g, tm); this.ter.frustumCulled = false;
    // orb
    this.orbU = { ...ctx.pal, uTime: { value: 0 }, uBright: { value: 0.6 } };
    this.orb = new THREE.Mesh(new THREE.PlaneGeometry(4.4, 4.4), new THREE.ShaderMaterial({ uniforms: this.orbU, vertexShader: ORB_VS, fragmentShader: ORB_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    this.orb.position.set(0, 10, -DEPTH + 10);
    this.orb.renderOrder = -10;
    this.scene.add(this.orb, this.ter);
    this.speed = new Spring(4, 3, 6); this.scroll = 0; this.orbS = new Spring(3, 2.5, 1); this.flash = 0;
  }
  setQuality() {}
  resize(w, h) {
    super.resize(w, h);
    this.bg.material.uniforms.uAspect.value = w / h;
    // horizon screen position for the sky gradient
    const v = new THREE.Vector3(0, 0, -DEPTH + 8).project(this.camera);
    this.skyU.uHorizon.value = v.y * 0.5 + 0.5;
  }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    if (hit) { this.speed.kick(hit * 18 * P.intensity); this.flash = Math.max(this.flash, hit * 0.8); }
    this.flash *= Math.exp(-rdt * 4);
    const v = Math.max(2, this.speed.step(6 + s.rms * 14 * P.intensity, rdt)) * P.motionAmount;
    this.scroll += v * dt;
    if (this.scroll > 20000) this.scroll -= 20000; // float-safety wrap (grid stays continuous; terrain noise re-phases once per ~40 min)
    const u = this.terU;
    u.uScroll.value = this.scroll; u.uBass.value = s.bass * P.intensity; u.uAmp.value = 0.85 + s.mid * 0.3; u.uLine.value = (0.85 + s.mid * 0.4) * P.opacity; u.uFlash.value = this.flash;
    const e = Math.max(s.stationActivity, s.energy * 0.8);
    const sz = this.orbS.step(0.85 + e * 0.35 + s.bass * 0.08, rdt);
    this.orb.scale.setScalar(sz * 23);
    this.orb.position.y = sz * 23 * 0.3;
    this.orbU.uBright.value = 0.35 + e * 0.9 + s.beat * 0.25; this.orbU.uTime.value = this.t;
    const c = this.camera;
    c.position.set(Math.sin(this.t * 0.07) * 1.2, 3.4 + Math.sin(this.t * 0.11) * 0.25, 6);
    c.lookAt(c.position.x * 0.5, 4.2, -60);
    this.bg.material.uniforms.uTime.value = this.t;
    const hv = this._hv || (this._hv = new THREE.Vector3());
    hv.set(c.position.x, 0, -DEPTH + 8).project(c);
    this.skyU.uHorizon.value = hv.y * 0.5 + 0.5;
  }
}
