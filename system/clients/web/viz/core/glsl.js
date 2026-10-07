// Shared GLSL snippets + fullscreen helpers.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

export const PAL_DECL = `uniform vec3 uBg0, uBg1, uC1, uC2, uC3, uHi;`;

export const HASH = `
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ s += a * vnoise(p); p = p * 2.03 + 17.1; a *= 0.5; } return s; }
`;

// Ashima / Stefan Gustavson 3D simplex noise (MIT)
export const NOISE3 = `
vec3 mod289(vec3 x){ return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x){ return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x){ return mod289(((x * 34.0) + 10.0) * x); }
vec4 taylorInvSqrt(vec4 r){ return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v){
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.5 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 105.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

// default backdrop: deep gradient with a soft glow below centre
export const BG_FN = `
vec3 vizBg(vec2 uv, float t){
  vec2 q = (uv - vec2(0.5, 0.36)) * vec2(1.2, 1.0);
  float r = length(q);
  vec3 c = mix(uBg1, uBg0, smoothstep(0.0, 0.9, r));
  c += uC1 * 0.06 * (vnoise(uv * vec2(3.0, 2.0) + vec2(t * 0.02, -t * 0.015)) - 0.3);
  c *= 1.0 - 0.3 * smoothstep(0.55, 1.1, length(uv - 0.5) * 1.4);
  return c;
}
`;

export const FS_VERT = `varying vec2 vUv; void main(){ vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

export function makeFSTri(material) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3));
  const m = new THREE.Mesh(g, material);
  m.frustumCulled = false;
  return m;
}

// fullscreen background mesh, drawn first in a mode's scene
export function makeBackdrop(pal, extraUniforms = {}, frag = null) {
  const uniforms = { ...pal, uTime: { value: 0 }, uAspect: { value: 1 }, ...extraUniforms };
  const fragmentShader = frag || `${PAL_DECL} uniform float uTime; varying vec2 vUv; ${HASH} ${BG_FN}
    void main(){ gl_FragColor = vec4(vizBg(vUv, uTime), 1.0); }`;
  const mat = new THREE.ShaderMaterial({ uniforms, vertexShader: FS_VERT, fragmentShader, depthTest: false, depthWrite: false });
  mat.extensions.derivatives = true;
  const m = makeFSTri(mat);
  m.renderOrder = -1000;
  return m;
}

// 64x1 RGBA8 texture holding the (mode-scaled) spectrum in .r
export function makeFFTTexture(n = 64) {
  const data = new Uint8Array(n * 4);
  const tex = new THREE.DataTexture(data, n, 1, THREE.RGBAFormat);
  tex.magFilter = tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return {
    tex,
    update(fft) {
      for (let i = 0; i < n; i++) { const v = fft[i] * 255; data[i * 4] = v > 255 ? 255 : v < 0 ? 0 : v; }
      tex.needsUpdate = true;
    },
  };
}
