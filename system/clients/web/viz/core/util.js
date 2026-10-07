// Small math helpers shared by the modes. No allocations in the per-frame paths.

export class Spring {
  constructor(k = 30, d = 8, x = 0) { this.k = k; this.d = d; this.x = x; this.v = 0; }
  step(target, dt) {
    // semi-implicit Euler, sub-stepped so large dt stays stable
    const n = dt > 1 / 30 ? Math.ceil(dt * 60) : 1, h = dt / n;
    for (let i = 0; i < n; i++) { const a = this.k * (target - this.x) - this.d * this.v; this.v += a * h; this.x += this.v * h; }
    return this.x;
  }
  kick(v) { this.v += v; }
}

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, t) => a + (b - a) * t;
export const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
export function damp(cur, target, tau, dt) { return tau <= 0 ? target : cur + (target - cur) * (1 - Math.exp(-dt / tau)); }

export function rng(seed = 1) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 2D value noise in [-1, 1]
const PERM = new Uint8Array(512), GRAD = new Float32Array(256);
{
  const r = rng(1337), p = [...Array(256).keys()];
  for (let i = 255; i > 0; i--) { const j = (r() * (i + 1)) | 0; const t = p[i]; p[i] = p[j]; p[j] = t; }
  for (let i = 0; i < 512; i++) PERM[i] = p[i & 255];
  for (let i = 0; i < 256; i++) GRAD[i] = r() * 2 - 1;
}
export function noise2(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const X = xi & 255, Y = yi & 255;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = GRAD[PERM[X + PERM[Y]]], b = GRAD[PERM[X + 1 + PERM[Y]]];
  const c = GRAD[PERM[X + PERM[Y + 1]]], d = GRAD[PERM[X + 1 + PERM[Y + 1]]];
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

export function disposeObject(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const m = o.material;
    if (m) (Array.isArray(m) ? m : [m]).forEach((x) => {
      for (const k in x) { const v = x[k]; if (v && v.isTexture) v.dispose(); }
      if (x.uniforms) for (const k in x.uniforms) { const v = x.uniforms[k].value; if (v && v.isTexture) v.dispose(); }
      x.dispose();
    });
  });
}
