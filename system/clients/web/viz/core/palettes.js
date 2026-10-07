import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

// Colors are display values (no sRGB->linear conversion anywhere in the pipeline).
// bg0 = darkest backdrop, bg1 = backdrop glow, c1 = primary, c2 = secondary/bright, c3 = accent, hi = highlight
export const PALETTES = {
  "PlayStation Blue": { bg0: 0x020516, bg1: 0x0b2a78, c1: 0x1f56e8, c2: 0x2fd2ff, c3: 0x7d63ff, hi: 0xf2f8ff },
  "Neon": { bg0: 0x06010d, bg1: 0x2a0a40, c1: 0xff2fbf, c2: 0x1ff4ff, c3: 0xb6ff3a, hi: 0xffffff },
  "Monochrome": { bg0: 0x040404, bg1: 0x24272c, c1: 0x6d737c, c2: 0xc9ced6, c3: 0x9aa0a8, hi: 0xffffff },
  "Radio Night": { bg0: 0x08040e, bg1: 0x2c1233, c1: 0xd4542b, c2: 0xffb347, c3: 0xff4f7b, hi: 0xfff1dc },
};
export const PALETTE_NAMES = Object.keys(PALETTES);
const KEYS = { bg0: "uBg0", bg1: "uBg1", c1: "uC1", c2: "uC2", c3: "uC3", hi: "uHi" };

const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
export function resolvePalette(name) {
  const k = norm(name);
  if (!k) return PALETTE_NAMES[0];
  return PALETTE_NAMES.find((n) => norm(n) === k) || PALETTE_NAMES.find((n) => norm(n).startsWith(k)) ||
    (k.startsWith("ps") ? PALETTE_NAMES[0] : PALETTE_NAMES[0]);
}

export function makePaletteUniforms() {
  const u = {};
  for (const k in KEYS) u[KEYS[k]] = { value: new THREE.Color() };
  return u;
}

const tmp = new THREE.Color();
// writes palette `name` into target colors (or lerps by t when t < 1)
export function applyPalette(uniforms, name, t = 1) {
  const p = PALETTES[resolvePalette(name)];
  for (const k in KEYS) {
    const h = p[k];
    tmp.setRGB(((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255, THREE.LinearSRGBColorSpace);
    if (t >= 1) uniforms[KEYS[k]].value.copy(tmp); else uniforms[KEYS[k]].value.lerp(tmp, t);
  }
}
