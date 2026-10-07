// 6 Anime Ink Wave: procedural cel-shaded illustration (single fragment shader): ink-outlined waves, painted foam,
// brush strokes, stylised clouds + moon. Secondary elements (foam, clouds, sparkles, spray) animate "on twos" (12 fps).
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { HASH, PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring } from "../core/util.js";

const FS = `${PAL_DECL}
uniform float uTime, uStep, uAspect, uBass, uMid, uTreble, uSplash, uAmp, uPx;
varying vec2 vUv;
${HASH}
// constant-pixel-width ink line around the zero set of d
float inkLine(float d, float px){ float w = abs(d) / max(fwidth(d), 1e-5); return 1.0 - smoothstep(px - 0.75, px + 0.75, w); }
float fillAA(float d){ return clamp(d / max(fwidth(d), 1e-5) + 0.5, 0.0, 1.0); }
float wave(float x, float t, float k, float amp, float base){
  return base + amp * (sin(x * k + t) * 0.6 + sin(x * k * 2.13 - t * 1.37 + 1.1) * 0.22 + sin(x * k * 0.47 + t * 0.61 + 2.3) * 0.38);
}
// stylised cumulus: flat bottom, scalloped puffy top, lit rim from above, ink outline; gaps between clouds
vec3 cloudLayer(vec3 col, vec2 p, float cy, float sc, float drift, float seed, vec3 body, vec3 lit, vec3 ink){
  float x = p.x * sc + drift;
  float cov = smoothstep(0.45, 0.68, vnoise(vec2(x * 0.9, seed)));
  float puff = 0.045 * vnoise(vec2(x * 3.0, seed + 3.0)) + 0.02 * abs(sin(x * 15.0 + vnoise(vec2(x * 2.0, seed)) * 6.0));
  float top = cy - 0.008 + (0.012 + puff) * cov / sc * 2.0;
  float bot = cy - 0.006 * cov - 0.004 * vnoise(vec2(x * 8.0, seed + 9.0));
  float d = min(top - p.y, p.y - bot);
  float rim = top - p.y;
  vec3 c = mix(lit, body, smoothstep(0.006, 0.012, rim));
  c = mix(c, body * 0.75, smoothstep(0.004, 0.0, p.y - bot) );
  col = mix(col, c, fillAA(d));
  col = mix(col, ink, inkLine(d, 0.9) * 0.85);
  return col;
}void main(){
  vec2 p = (vUv - 0.5) * vec2(uAspect, 1.0);   // y in [-0.5, 0.5]
  float t = uTime, ts = uStep;
  vec3 ink = uBg0 * 0.35 + vec3(0.01, 0.01, 0.03);
  // ---- sky
  vec3 col = mix(mix(uBg1, uC2, 0.22), uBg0, smoothstep(0.0, 0.95, vUv.y));
  col = mix(col, mix(uBg1, uC1, 0.35), smoothstep(0.42, 0.3, vUv.y) * 0.5);
  // painted sky streaks
  float st = vnoise(vec2(p.x * 2.5 + ts * 0.05, p.y * 34.0));
  col = mix(col, mix(col, uC2, 0.35), smoothstep(0.7, 0.85, st) * smoothstep(0.5, 0.0, abs(p.y - 0.18)) * 0.45);
  // stars (stepped twinkle)
  vec2 sg = floor(p * 70.0);
  float sh = hash12(sg);
  if (sh > 0.986 && p.y > 0.02) {
    vec2 sc = fract(p * 70.0) - 0.5;
    float tw = step(0.35, fract(sh * 13.0 + ts * 0.5));
    float star = max(smoothstep(0.09, 0.0, abs(sc.x)) * smoothstep(0.35, 0.0, abs(sc.y)), smoothstep(0.09, 0.0, abs(sc.y)) * smoothstep(0.35, 0.0, abs(sc.x)));
    col = mix(col, uHi, star * tw * (0.5 + uTreble * 0.5));
  }
  // ---- moon with banded cel halo
  vec2 mc = vec2(uAspect * 0.3, 0.27); float mr = 0.075;
  float md = length(p - mc) - mr;
  float halo = floor(clamp(1.0 - md / 0.16, 0.0, 1.0) * 3.0) / 3.0;
  col = mix(col, mix(col, mix(uHi, uC2, 0.4), 0.55), halo * 0.35 * step(0.0, md));
  vec3 moon = mix(uHi, uC2, 0.1);
  moon = mix(moon, mix(uHi, uC1, 0.3), step(0.6, fbm((p - mc) * 16.0 + 3.0)) * 0.5);
  moon = mix(moon, mix(uC2, uC1, 0.45), step(mr, length(p - mc - vec2(0.028, 0.022))) * 0.5);
  col = mix(col, moon, fillAA(-md));
  col = mix(col, ink, inkLine(md, 1.2));
  // ---- clouds (drift on twos)
  col = cloudLayer(col, p, 0.36, 2.0, ts * 0.03, 1.7, mix(uBg1, uC1, 0.35), mix(uC2, uHi, 0.6), ink);
  col = cloudLayer(col, p, 0.2, 2.6, -ts * 0.04, 7.3, mix(uBg1, uC1, 0.2) * 0.9, mix(uC2, uHi, 0.35), ink);
  // ---- far wave
  float h3 = wave(p.x, t * 0.5, 7.0, 0.012 * (1.0 + uBass), -0.1);
  float d3 = h3 - p.y;
  col = mix(col, mix(uC1, uBg1, 0.5), fillAA(d3));
  col = mix(col, mix(uC2, uHi, 0.3), fillAA(d3) * (1.0 - fillAA(d3 - 0.006)) * 0.8);
  col = mix(col, ink, inkLine(d3, 0.8) * 0.8);
  // ---- mid wave with foam rim
  float h2 = wave(p.x + 0.7, t * 0.7, 4.5, (0.022 + uBass * 0.02) * uAmp, -0.17);
  float d2 = h2 - p.y;
  vec3 w2 = mix(uC1, uC2, 0.25);
  w2 = mix(w2, mix(uC1, uBg0, 0.35), fillAA(d2 - 0.045 - 0.01 * sin(p.x * 13.0 + t)));
  col = mix(col, w2, fillAA(d2));
  float fn2 = vnoise(vec2(p.x * 26.0 + ts * 1.5, ts * 0.7));
  float f2 = min(d2 + 0.003, 0.012 + 0.012 * fn2 - d2);
  col = mix(col, uHi, fillAA(f2) * 0.95);
  col = mix(col, ink, inkLine(d2, 1.1));
  // ---- front wave: big cel-shaded body
  float A1 = (0.055 + uBass * 0.05) * uAmp;
  float h1 = wave(p.x - 0.3, t * 0.9, 2.6, A1, -0.29) + pow(max(0.0, sin(p.x * 2.6 + t * 0.9 - 0.6)), 8.0) * 0.045 * uAmp;
  float d1 = h1 - p.y;
  float wob = 0.012 * sin(p.x * 9.0 + t * 0.7) + 0.012 * vnoise(vec2(p.x * 10.0, ts * 0.8));
  float b1 = d1 - 0.035 - wob, b2 = d1 - 0.11 - wob * 1.6;
  vec3 w1 = mix(uC2, uHi, 0.12);
  w1 = mix(w1, uC1, fillAA(b1));
  w1 = mix(w1, mix(uC1, uBg0, 0.5), fillAA(b2));
  // brush strokes following the wave
  float br = vnoise(vec2(p.x * 5.0 + d1 * 4.0, d1 * 70.0 + ts * 0.4));
  w1 = mix(w1, mix(w1, uC2, 0.5), smoothstep(0.7, 0.78, br) * fillAA(b1) * 0.8);
  float br2 = vnoise(vec2(p.x * 14.0 - ts * 0.3, d1 * 140.0));
  w1 = mix(w1, mix(w1, uBg0, 0.5), smoothstep(0.78, 0.86, br2) * fillAA(b2) * 0.6);
  col = mix(col, w1, fillAA(d1));
  col = mix(col, ink, inkLine(b1, 0.7) * fillAA(d1) * 0.55);
  col = mix(col, ink, inkLine(b2, 0.7) * fillAA(d1) * 0.45);
  col = mix(col, ink, inkLine(d1, 1.5));
  // painted foam riding the crest
  float fn = vnoise(vec2(p.x * 20.0 - ts * 1.2, ts * 0.5)) * 0.7 + vnoise(vec2(p.x * 55.0, ts)) * 0.3;
  float fTop = -0.004 - 0.014 * fn * (0.7 + uTreble * 0.6);
  float fBot = 0.012 + 0.03 * vnoise(vec2(p.x * 9.0 + 4.0, ts * 0.3));
  float fd = min(d1 - fTop, fBot - d1);
  col = mix(col, mix(uHi, uC2, 0.08), fillAA(fd));
  col = mix(col, ink, inkLine(fd, 1.0) * 0.9);
  // foam dots under the crest
  vec2 dg = p * vec2(80.0, 80.0);
  vec2 dc = floor(dg);
  float dh = hash12(dc + floor(ts * 2.0) * 7.0);
  float dd = length(fract(dg) - 0.5);
  float dotZone = smoothstep(0.015, 0.03, d1) * smoothstep(0.09, 0.04, d1);
  col = mix(col, uHi, step(0.86, dh) * smoothstep(0.32, 0.22, dd) * dotZone);
  // spray on beats (stepped)
  float sy = p.y - h1;
  vec2 sp = vec2(p.x * 40.0, sy * 40.0);
  float spH = hash12(floor(sp) + floor(ts * 6.0) * 3.1);
  float spray = step(1.0 - 0.18 * uSplash, spH) * smoothstep(0.35, 0.15, length(fract(sp) - 0.5)) * step(0.0, sy) * step(sy, 0.09 * uSplash);
  col = mix(col, uHi, spray);
  // paper grain + soft vignette
  float grain = hash12(floor(gl_FragCoord.xy / uPx)) * 0.06 + fbm(p * vec2(60.0, 8.0)) * 0.05;
  col *= 0.96 + grain;
  col *= 1.0 - 0.25 * smoothstep(0.45, 0.85, length((vUv - 0.5) * vec2(1.2, 1.0)));
  gl_FragColor = vec4(col, 1.0);
}`;

export default class AnimeInk extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1, 1);
    this.u = { uStep: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uSplash: { value: 0 }, uAmp: { value: 1 }, uPx: { value: 1 } };
    this.quad = makeBackdrop(ctx.pal, this.u, FS);
    this.scene.add(this.quad);
    this.u.uTime = this.quad.material.uniforms.uTime; this.u.uAspect = this.quad.material.uniforms.uAspect;
    this.bass = new Spring(5, 3.5, 0); this.splash = 0;
  }
  resize(w, h) { this.u.uAspect.value = w / h; this.u.uPx.value = Math.max(1, this.ctx.pr * 1.5); }
  update(s, dt, rdt) {
    const P = this.params;
    this.t += dt;
    const hit = this.beatHit(s, 0.3);
    if (hit) this.splash = Math.max(this.splash, hit * P.intensity);
    this.splash *= Math.exp(-rdt * 2.2);
    this.u.uTime.value = this.t;
    this.u.uStep.value = Math.floor(this.t * 12) / 12; // on twos
    this.u.uBass.value = Math.max(0, this.bass.step(s.bass * P.intensity, rdt));
    this.u.uMid.value = s.mid; this.u.uTreble.value = s.treble;
    this.u.uSplash.value = this.splash; this.u.uAmp.value = P.motionAmount * (0.85 + s.rms * 0.4);
  }
}
