/* gBox pad glyph: a small line-art diagram of the running game's real controller that lights what is pressed,
 * by the player (Gamepad API, through index.html's own mapping when present) or by gBox (agent / autoplay / UI buttons,
 * from GET /api/sessions/{sid}/pad, polled at 10 Hz only while visible).
 *
 *   const g = PadGlyph.mount(el, "n64", { sid })   // platform may be null: taken from the session via /pad
 *   PadGlyph.update({ held: ["b", "up"], stick: { x: .7, y: 0 }, source: "agent" })   // manual layer (all glyphs)
 *   PadGlyph.local = () => ({ held: Set|[], stick: {x, y}, rstick: {x, y} }) | null      // optional: own pad reader
 *                                                     (index.html sets it: Player 1 through the console's controller map)
 * Right-click on a part = index.html's "Map <button> to…" dialog (clients/web/viz/pad-map.js); data-k's first key is the
 * RetroPad input that part is, e.g. N64 C-up = "rup" (the right stick).
 *
 * Keys are RetroPad names (a b x y l r l2 r2 l3 r3 start select up down left right lup ldown lleft lright ...).
 * RetroPad -> console button follows each libretro core's defaults (positional SNES layout); standalone emulators that
 * bind by name (Dolphin, DuckStation, MAME adapters) get their own variant.
 *
 * Real-controller art: clients/web/glyphs/<key>.svg (one per console, drawn by glyphs/draw.py), embedded below by
 * glyphs/embed.py. Their parts carry data-btn="<console button name>"; GLYPH_DEFS maps those names to RetroPad keys.
 * Platforms without an SVG glyph (DS, 3DS, unknown) keep the built-in LAYOUTS drawing.
 */
(() => {
"use strict";
const VB_W = 260, VB_H = 170, DZ = 0.12;
const GREY = "var(--pg-lit)";          // neutral buttons: lit in the theme's foreground colour
const C = {
  n64A: "#3d6fe0", n64B: "#2e9e57", n64C: "#f2c230", n64S: "#d8453a",
  sfcA: "#d8333a", sfcB: "#e8c228", sfcX: "#3b5fd6", sfcY: "#2fa34a", nes: "#d8333a",
  psT: "#3ab795", psO: "#e2554a", psX: "#7d9cf0", psS: "#e07fbf",
  dcA: "#e0453a", dcB: "#3b6fd6", dcX: "#e7c33a", dcY: "#3aa55a",
  gcA: "#2fae6c", gcB: "#e0453a", gcZ: "#8a6cf0", gcC: "#f2c230",
  xA: "#3fae49", xB: "#e04b3a", xX: "#3a78d6", xY: "#e8b93a",
  gb: "#c23a7e", gba: "#b9b4e6", red: "#e0453a",
};

// ---------- parts ----------
const btn = (k, x, y, r, label, c, o) => ({ t: "btn", k, x, y, r, label, c, ...o });
const sym = (k, x, y, r, s, c, o) => ({ t: "sym", k, x, y, r, s, c, ...o });
const pill = (k, x, y, w, h, label, c, o) => ({ t: "pill", k, x, y, w, h, label, c, ...o });
const dpad = (x, y, s, o) => ({ t: "dpad", x, y, s, ...o });
const stick = (id, x, y, r, c, o) => ({ t: "stick", id, x, y, r, c, ...o });
const n = v => Math.round(v * 100) / 100;
const txt = (x, y, s, fs, cls = "pg-t") => `<text class="${cls}" x="${n(x)}" y="${n(y)}" font-size="${n(fs)}">${s}</text>`;
const deco = s => `<g class="pg-d">${s}</g>`;

function glyph(s, x, y, d) {          // PS symbols and C-button arrows
  switch (s) {
    case "cross": return `<path class="pg-y" d="M${n(x - d)} ${n(y - d)}L${n(x + d)} ${n(y + d)}M${n(x + d)} ${n(y - d)}L${n(x - d)} ${n(y + d)}"/>`;
    case "circle": return `<circle class="pg-y" cx="${x}" cy="${y}" r="${n(d)}"/>`;
    case "square": return `<rect class="pg-y" x="${n(x - d * .85)}" y="${n(y - d * .85)}" width="${n(d * 1.7)}" height="${n(d * 1.7)}"/>`;
    case "triangle": return `<path class="pg-y" d="M${x} ${n(y - d * 1.05)}L${n(x + d)} ${n(y + d * .7)}L${n(x - d)} ${n(y + d * .7)}Z"/>`;
    default: {                        // arrow u/d/l/r
      const a = { u: 0, r: 90, d: 180, l: 270 }[s] || 0;
      return `<path class="pg-a" transform="rotate(${a} ${x} ${y})" d="M${x} ${n(y - d)}L${n(x + d * .9)} ${n(y + d * .6)}L${n(x - d * .9)} ${n(y + d * .6)}Z"/>`;
    }
  }
}

function partSVG(p, variant) {
  const k = (p.alt && p.alt[variant]) || p.k || "", c = p.c || GREY, nt = p.c ? "" : " nt", open = `<g class="pg-b${nt}" data-k="${k}" style="--c:${c}">`;
  const cap = p.cap ? txt(p.x, p.y + (p.h || p.r * 2) / 2 + 5.5, p.cap, 4.6, "pg-c") : "";
  if (p.t === "btn")
    return open + `<circle class="pg-s" cx="${p.x}" cy="${p.y}" r="${p.r}"/>` +
      (p.label ? txt(p.x, p.y + .4, p.label, p.fs || p.r * 1.05) : "") + `</g>` + cap;
  if (p.t === "sym")
    return open + `<circle class="pg-s" cx="${p.x}" cy="${p.y}" r="${p.r}"/>` + glyph(p.s, p.x, p.y, p.r * (p.s.length === 1 ? .5 : .45)) + `</g>` + cap;
  if (p.t === "pill") {
    const rot = p.rot ? ` transform="rotate(${p.rot} ${p.x} ${p.y})"` : "";
    return open + `<rect class="pg-s" x="${n(p.x - p.w / 2)}" y="${n(p.y - p.h / 2)}" width="${p.w}" height="${p.h}" rx="${n(Math.min(p.w, p.h) / 2)}"${rot}/>` +
      (p.label ? txt(p.x, p.y + .3, p.label, p.fs || Math.min(p.h * .8, 7.5)) : "") + `</g>` + cap;
  }
  if (p.t === "dpad") {
    const { x, y, s } = p, h = s / 2, L = 1.5 * s, arms = [["up", x - h, y - L, "u"], ["down", x - h, y + h, "d"], ["left", x - L, y - h, "l"], ["right", x + h, y - h, "r"]];
    return (p.round ? `<circle class="pg-dpb" cx="${x}" cy="${y}" r="${n(L + 4)}"/>` : "") +
      arms.map(([key, ax, ay, dir]) => `<g class="pg-b pg-arm nt" data-k="${key}" style="--c:${GREY}"><rect class="pg-s" x="${n(ax)}" y="${n(ay)}" width="${s}" height="${s}"/>` +
        glyph(dir, ax + h + (dir === "l" ? -s * .1 : dir === "r" ? s * .1 : 0), ay + h + (dir === "u" ? -s * .1 : dir === "d" ? s * .1 : 0), s * .22) + `</g>`).join("") +
      `<path class="pg-dpo" d="M${n(x - h)} ${n(y - L)}H${n(x + h)}V${n(y - h)}H${n(x + L)}V${n(y + h)}H${n(x + h)}V${n(y + L)}H${n(x - h)}V${n(y + h)}H${n(x - L)}V${n(y - h)}H${n(x - h)}Z"/>` +
      `<circle class="pg-dpc" cx="${x}" cy="${y}" r="${n(s * .22)}"/>`;
  }
  if (p.t === "stick") {
    const kr = p.kr || p.r * .62;
    const keys = p.k || (p.id === "l" ? "l3 lup ldown lleft lright" : "r3 rup rdown rleft rright cup cdown cleft cright");
    return `<g class="pg-b pg-stk${nt}" data-k="${keys}" style="--c:${c}"><circle class="pg-gate" cx="${p.x}" cy="${p.y}" r="${p.r}"/>` +
      `<g class="pg-knob" data-stick="${p.id}" data-m="${n(p.r - kr)}" data-dirs="${p.dirs ? 1 : 0}">` +
      `<circle class="pg-s" cx="${p.x}" cy="${p.y}" r="${n(kr)}"/><circle class="pg-kd" cx="${p.x}" cy="${p.y}" r="${n(kr * .55)}"/>` +
      (p.label ? txt(p.x, p.y + .3, p.label, kr * .9) : "") + `</g></g>`;
  }
  return "";
}

// ---------- layouts (viewBox 260 x 170) ----------
// parallel-n64 / mupen64plus-next: R2 = "C buttons mode" (B/Y/A/X become C-down/left/right/up)
function n64CMode(h) {
  if (!h.has("r2")) return h;
  const m = new Map(h);
  for (const [f, t] of [["b", "c_down"], ["y", "c_left"], ["a", "c_right"], ["x", "c_up"]]) if (m.has(f)) { m.set(t, m.get(f)); m.delete(f); }
  return m;
}
const body = d => `<path class="pg-body" d="${d}"/>`;
const PS_FACE = (x, y, d, r) => [
  sym("x", x, y - d, r, "triangle", C.psT, { alt: { duckstation: "y" } }),
  sym("a", x + d, y, r, "circle", C.psO, { alt: { duckstation: "b" } }),
  sym("b", x, y + d, r, "cross", C.psX, { alt: { duckstation: "a" } }),
  sym("y", x - d, y, r, "square", C.psS, { alt: { duckstation: "x" } }),
];
const LAYOUTS = {
  n64: () => ({
    name: "Nintendo 64",
    body: body("M30 30Q130 8 230 30Q252 38 250 62L236 150Q232 166 216 164Q200 162 198 146L186 96Q176 88 160 96L148 150Q144 166 130 166Q116 166 112 150L100 96Q84 88 74 96L62 146Q60 162 44 164Q28 166 24 150L10 62Q8 38 30 30Z"),
    parts: [
      pill("l", 42, 30, 34, 8, "L", null, { rot: -9 }), pill("r", 218, 30, 34, 8, "R", null, { rot: 9 }),
      dpad(54, 66, 11),
      btn("start", 130, 60, 6.5, "", C.n64S, { cap: "START" }),
      stick("l", 130, 116, 15),
      pill("l2", 130, 151, 20, 8, "Z"),
      btn("b", 186, 86, 10, "A", C.n64A), btn("y", 167, 68, 10, "B", C.n64B),
      sym("rup cup c_up", 216, 50, 6.5, "u", C.n64C), sym("rright cright c_right", 229, 63, 6.5, "r", C.n64C),
      sym("rdown cdown c_down", 216, 76, 6.5, "d", C.n64C), sym("rleft cleft c_left", 203, 63, 6.5, "l", C.n64C),
    ],
    remap: n64CMode,
  }),
  snes: () => ({
    name: "Super Nintendo",
    body: body("M62 40H198A50 50 0 0 1 198 140H62A50 50 0 0 1 62 40Z") + deco(`<circle cx="62" cy="90" r="33"/><circle cx="198" cy="90" r="36"/>`),
    parts: [
      pill("l", 58, 41, 58, 8, "L"), pill("r", 202, 41, 58, 8, "R"),
      dpad(62, 90, 14),
      pill("select", 114, 98, 18, 6.5, "", null, { rot: -28, cap: "SELECT" }), pill("start", 144, 98, 18, 6.5, "", null, { rot: -28, cap: "START" }),
      btn("x", 198, 68, 10, "X", C.sfcX), btn("a", 220, 90, 10, "A", C.sfcA),
      btn("b", 198, 112, 10, "B", C.sfcB), btn("y", 176, 90, 10, "Y", C.sfcY),
    ],
  }),
  nes: () => ({
    name: "NES",
    body: body("M16 46H244Q250 46 250 52V124Q250 130 244 130H16Q10 130 10 124V52Q10 46 16 46Z") +
      deco(`<rect x="96" y="58" width="68" height="8" rx="2"/><rect x="96" y="70" width="68" height="8" rx="2"/><rect x="170" y="80" width="68" height="36" rx="4"/>`),
    parts: [
      dpad(54, 90, 13),
      pill("select", 114, 100, 22, 7, "", null, { cap: "SELECT" }), pill("start", 146, 100, 22, 7, "", null, { cap: "START" }),
      btn("b", 186, 98, 11, "B", C.nes), btn("a", 222, 98, 11, "A", C.nes),
    ],
  }),
  md: () => ({   // genesis_plus_gx: Y=A B=B A=C L=X X=Y R=Z Select=Mode
    name: "Mega Drive / Genesis",
    body: body("M26 66Q28 34 72 34L188 34Q232 34 234 66Q238 110 214 136Q194 154 170 140L156 126L104 126L90 140Q66 154 46 136Q22 110 26 66Z"),
    parts: [
      dpad(70, 82, 12, { round: true }),
      pill("select", 130, 56, 16, 6, "", null, { cap: "MODE" }), pill("start", 130, 86, 22, 8, "", null, { cap: "START" }),
      btn("y", 166, 104, 9, "A"), btn("b", 188, 97, 9, "B"), btn("a", 210, 90, 9, "C"),
      btn("l", 160, 81, 6.5, "X"), btn("x", 181, 74, 6.5, "Y"), btn("r", 202, 67, 6.5, "Z"),
    ],
  }),
  saturn: () => ({   // yabasanshiro: B=A A=B L=C Y=X X=Y R=Z L2=L R2=R
    name: "Saturn",
    body: body("M28 62Q30 36 70 36L190 36Q230 36 232 62Q236 108 212 134Q192 152 168 138L154 124L106 124L92 138Q68 152 48 134Q24 108 28 62Z"),
    parts: [
      pill("l2", 62, 36, 50, 8, "L", null, { rot: -6 }), pill("r2", 198, 36, 50, 8, "R", null, { rot: 6 }),
      dpad(70, 82, 12, { round: true }),
      pill("start", 130, 94, 18, 7, "", null, { cap: "START" }),
      btn("b", 166, 100, 8.5, "A"), btn("a", 186, 94, 8.5, "B"), btn("l", 206, 88, 8.5, "C"),
      btn("y", 160, 78, 6, "X"), btn("x", 180, 72, 6, "Y"), btn("r", 200, 66, 6, "Z"),
    ],
  }),
  ps: () => ({
    name: "PlayStation DualShock",
    body: body("M60 40L200 40Q232 40 240 70L252 130Q256 160 230 160Q212 160 202 140L190 128L70 128L58 140Q48 160 30 160Q4 160 8 130L20 70Q28 40 60 40Z"),
    parts: [
      pill("l2", 58, 21, 34, 8, "L2"), pill("l", 58, 32, 38, 7, "L1"), pill("r2", 202, 21, 34, 8, "R2"), pill("r", 202, 32, 38, 7, "R1"),
      dpad(56, 74, 11),
      pill("select", 112, 70, 14, 6, "", null, { cap: "SELECT" }), pill("start", 148, 70, 14, 6, "", null, { cap: "START" }),
      ...PS_FACE(204, 74, 17, 8.5),
      stick("l", 100, 108, 13), stick("r", 160, 108, 13),
    ],
  }),
  psp: () => ({
    name: "PSP",
    body: body("M52 42H208A46 46 0 0 1 208 134H52A46 46 0 0 1 52 42Z") + deco(`<rect x="72" y="50" width="116" height="76" rx="3"/>`),
    parts: [
      pill("l", 44, 43, 40, 6, "L", null, { rot: -12 }), pill("r", 216, 43, 40, 6, "R", null, { rot: 12 }),
      dpad(36, 76, 9),
      stick("l", 38, 112, 8.5, null, { kr: 5.5 }),
      ...PS_FACE(224, 80, 12, 5.5),
      pill("select", 208, 116, 10, 4.5, "", null, { cap: "SELECT" }), pill("start", 232, 116, 10, 4.5, "", null, { cap: "START" }),
    ],
  }),
  dc: () => ({   // flycast: B=A A=B Y=X X=Y L2/R2 = triggers
    name: "Dreamcast",
    body: body("M44 38Q130 26 216 38Q246 44 246 78L238 138Q234 162 212 160Q194 158 188 140L178 120L82 120L72 140Q66 158 48 160Q26 162 22 138L14 78Q14 44 44 38Z") +
      deco(`<rect x="110" y="42" width="40" height="52" rx="4"/><rect x="117" y="50" width="26" height="20" rx="2"/>`),
    parts: [
      pill("l2", 54, 32, 40, 8, "L", null, { rot: -6 }), pill("r2", 206, 32, 40, 8, "R", null, { rot: 6 }),
      stick("l", 58, 66, 14),
      dpad(78, 104, 9.5),
      btn("start", 130, 104, 5.5, "", null, { cap: "START" }),
      btn("x", 206, 59, 8, "Y", C.dcY), btn("a", 223, 76, 8, "B", C.dcB),
      btn("b", 206, 93, 8, "A", C.dcA), btn("y", 189, 76, 8, "X", C.dcX),
    ],
  }),
  gc: () => ({   // dolphin libretro: names match (A=A ...), R1=Z L2=L R2=R right stick = C; standalone Dolphin: l/r = L/R, z = Z
    name: "GameCube",
    body: body("M52 40Q130 30 208 40Q244 46 246 86L240 136Q236 160 212 158Q196 156 190 138L180 118L80 118L70 138Q64 156 48 158Q24 160 20 136L14 86Q16 46 52 40Z"),
    parts: [
      pill("l2", 52, 34, 40, 8, "L", null, { rot: -6, alt: { dolphin: "l l2" } }),
      pill("r2", 208, 35, 40, 8, "R", null, { rot: 6, alt: { dolphin: "r r2" } }),
      pill("r", 212, 25, 28, 6.5, "Z", C.gcZ, { rot: 6, alt: { dolphin: "z select" } }),
      stick("l", 56, 74, 15),
      dpad(88, 104, 8),
      btn("start", 130, 76, 5, "", null, { cap: "START" }),
      stick("r", 160, 104, 11, C.gcC, { label: "C" }),
      btn("a", 206, 84, 13, "A", C.gcA), btn("b", 184, 101, 7.5, "B", C.gcB),
      pill("x", 232, 76, 22, 9.5, "X", null, { rot: 78 }), pill("y", 202, 60, 22, 9.5, "Y", null, { rot: -12 }),
    ],
  }),
  wii: () => ({   // ponytail: Dolphin's Wiimote+Nunchuk binds vary per setup; RetroPad names map onto the obvious buttons
    name: "Wii Remote + Nunchuk",
    body: body("M160 10H176Q190 10 190 24V148Q190 162 176 162H160Q146 162 146 148V24Q146 10 160 10Z") +
      body("M50 40Q90 18 112 46Q128 70 112 104Q98 134 76 150Q58 160 46 146Q36 130 40 104Q30 70 50 40Z") +
      deco(`<path d="M62 154Q100 176 156 162" fill="none"/><circle cx="168" cy="20" r="2.5"/><circle cx="168" cy="114" r="1.6"/>`),
    parts: [
      dpad(168, 44, 9),
      btn("a", 168, 74, 9, "A"),
      pill("b", 198, 74, 7, 18, "B", null, { fs: 5.5 }),
      btn("select", 155, 98, 4.5, "−", null, { fs: 7 }), btn("", 168, 98, 4.5, "⌂", null, { fs: 5 }), btn("start", 181, 98, 4.5, "+", null, { fs: 7 }),
      btn("x", 168, 128, 6, "1"), btn("y", 168, 145, 6, "2"),
      stick("l", 76, 62, 13),
      btn("l", 104, 90, 5.5, "C"), pill("l2", 104, 106, 14, 8, "Z"),
    ],
  }),
  gb: () => ({
    name: "Game Boy",
    body: body("M84 6H176Q184 6 184 14V140Q184 164 160 164H84Q76 164 76 156V14Q76 6 84 6Z") +
      deco(`<path d="M90 16H170V70Q170 80 160 80H90Z"/><rect x="104" y="24" width="52" height="44"/><path d="M158 150L170 138M163 154L175 142M168 158L178 148" />`),
    parts: [
      dpad(102, 110, 10),
      btn("b", 142, 116, 8, "B", C.gb), btn("a", 164, 106, 8, "A", C.gb),
      pill("select", 118, 140, 14, 5, "", null, { rot: -28, cap: "SELECT" }), pill("start", 138, 140, 14, 5, "", null, { rot: -28, cap: "START" }),
    ],
  }),
  gba: () => ({
    name: "Game Boy Advance",
    body: body("M40 44L220 44Q252 44 252 80L252 108Q252 140 220 140L40 140Q8 140 8 108L8 80Q8 44 40 44Z") +
      deco(`<rect x="70" y="50" width="120" height="84" rx="8"/><rect x="86" y="60" width="88" height="62"/>`),
    parts: [
      pill("l", 36, 45, 40, 6, "L", null, { rot: -10 }), pill("r", 224, 45, 40, 6, "R", null, { rot: 10 }),
      dpad(40, 84, 10),
      btn("select", 30, 120, 3.5, "", null, { cap: "SELECT" }), btn("start", 50, 120, 3.5, "", null, { cap: "START" }),
      btn("a", 230, 80, 8, "A", C.gba), btn("b", 211, 94, 8, "B", C.gba),
    ],
  }),
  ds: () => DS(false),
  "3ds": () => DS(true),
  arcade: () => ({   // libretro MAME / Flycast NAOMI: B=1 A=2 Y=3 X=4 L=5 R=6; standalone MAME binds a=1 b=2 x=3 y=4
    name: "Arcade",
    body: body("M18 30H242Q252 30 252 40V140Q252 150 242 150H18Q8 150 8 140V40Q8 30 18 30Z") + deco(`<rect x="14" y="36" width="232" height="108" rx="6"/>`),
    parts: [
      stick("l", 62, 94, 28, C.red, { kr: 13, dirs: true, k: "lup ldown lleft lright up down left right" }),
      pill("select", 182, 46, 22, 8, "COIN"), pill("start", 214, 46, 22, 8, "START"),
      btn("b", 132, 84, 11, "1", null, { alt: { mame: "a" } }), btn("a", 160, 76, 11, "2", null, { alt: { mame: "b" } }),
      btn("y", 189, 76, 11, "3", null, { alt: { mame: "x" } }),
      btn("x", 128, 112, 11, "4", null, { alt: { mame: "y" } }), btn("l", 156, 104, 11, "5"), btn("r", 185, 104, 11, "6"),
    ],
  }),
  xbox: () => ({
    name: "Controller",
    body: body("M64 40L196 40Q228 40 238 66L254 128Q260 160 232 162Q214 163 204 144L192 124L68 124L56 144Q46 163 28 162Q0 160 6 128L22 66Q32 40 64 40Z") +
      deco(`<circle cx="130" cy="52" r="7"/>`),
    parts: [
      pill("l2", 62, 22, 30, 8, "LT"), pill("l", 62, 33, 40, 7, "LB"), pill("r2", 198, 22, 30, 8, "RT"), pill("r", 198, 33, 40, 7, "RB"),
      stick("l", 60, 72, 13), dpad(96, 104, 9), stick("r", 164, 104, 13),
      btn("select", 115, 72, 4.5, "", null, { cap: "VIEW" }), btn("start", 145, 72, 4.5, "", null, { cap: "MENU" }),
      btn("x", 204, 56, 7.5, "Y", C.xY), btn("a", 219, 71, 7.5, "B", C.xB), btn("b", 204, 86, 7.5, "A", C.xA), btn("y", 189, 71, 7.5, "X", C.xX),
    ],
  }),
};
function DS(three) {
  return {
    name: three ? "Nintendo 3DS" : "Nintendo DS",
    body: body("M62 4H198Q204 4 204 10V66Q204 72 198 72H62Q56 72 56 66V10Q56 4 62 4Z") +
      body("M28 76H232Q240 76 240 84V158Q240 166 232 166H28Q20 166 20 158V84Q20 76 28 76Z") +
      deco(`<rect x="${three ? 82 : 94}" y="10" width="${three ? 96 : 72}" height="56"/><rect x="94" y="84" width="72" height="54"/>`),
    parts: [
      pill("l", 42, 77, 34, 6, "L"), pill("r", 218, 77, 34, 6, "R"),
      ...(three ? [pill("l2", 74, 77, 18, 5, "ZL", null, { fs: 4 }), pill("r2", 186, 77, 18, 5, "ZR", null, { fs: 4 }),
        stick("l", 52, 102, 11, null, { kr: 7.5 }), dpad(52, 140, 8)] : [dpad(52, 116, 10)]),
      btn("x", 208, 96, 6.5, "X"), btn("a", 222, 110, 6.5, "A"), btn("b", 208, 124, 6.5, "B"), btn("y", 194, 110, 6.5, "Y"),
      btn("select", 196, 150, 3.5, "", null, { cap: "SELECT" }), btn("start", 216, 150, 3.5, "", null, { cap: "START" }),
    ],
  };
}

const FAMILY = {
  n64: "n64", n64dd: "n64", snes: "snes", sfc: "snes", sgb: "snes", satellaview: "snes", nes: "nes", fds: "nes", famicom: "nes",
  genesis: "md", megadrive: "md", md: "md", segacd: "md", sega32x: "md", segapico: "md", sms: "md", sg1000: "md", gamegear: "md",
  saturn: "saturn", psx: "ps", ps1: "ps", ps2: "ps", ps3: "ps", playstation: "ps", psp: "psp",
  dreamcast: "dc", dc: "dc", naomi: "arcade", atomiswave: "arcade", arcade: "arcade", mame: "arcade", neogeo: "arcade", cps1: "arcade",
  cps2: "arcade", cps3: "arcade", fbneo: "arcade", gamecube: "gc", gc: "gc", ngc: "gc", wii: "wii", gb: "gb", gbc: "gb",
  gba: "gba", nds: "ds", ds: "ds", "3ds": "3ds", n3ds: "3ds",
};
const famOf = p => FAMILY[String(p || "").toLowerCase().replace(/[^a-z0-9]/g, "")] || "xbox";
const VARIANT = { dolphin: "dolphin", duckstation: "duckstation", mame: "mame" };      // adapters that bind by name

// ---------- real-controller SVG glyphs ----------
/* GLYPHS-BEGIN (generated by glyphs/embed.py from glyphs/*.svg: edit those, then re-run it) */
const SVG = {
  "arcade": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"arcade\" data-name=\"Arcade stick\"><path class=\"pg-body\" d=\"M18 34H242Q252 34 252 44V146Q252 156 242 156H18Q8 156 8 146V44Q8 34 18 34Z\"/><g class=\"pg-d\"><rect x=\"16\" y=\"42\" width=\"228\" height=\"106\" rx=\"5\"/></g><g id=\"arcade-stick\" data-btn=\"stick\" data-stick=\"s\" data-travel=\"16\" data-c=\"#e0453a\" data-dirs=\"1\"><circle class=\"pg-gate\" cx=\"60\" cy=\"98\" r=\"28\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"60\" cy=\"98\" r=\"12\"/><circle class=\"pg-kd\" cx=\"60\" cy=\"98\" r=\"6.6\"/></g></g><g id=\"arcade-coin\" data-btn=\"coin\"><rect class=\"pg-s\" x=\"188\" y=\"44.5\" width=\"16\" height=\"7\" rx=\"3.5\"/></g><g id=\"arcade-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"216\" y=\"44.5\" width=\"16\" height=\"7\" rx=\"3.5\"/></g><text class=\"pg-c\" x=\"196\" y=\"57\" font-size=\"4.2\">COIN</text><text class=\"pg-c\" x=\"224\" y=\"57\" font-size=\"4.2\">START</text><g id=\"arcade-b1\" data-btn=\"b1\"><circle class=\"pg-s\" cx=\"124\" cy=\"86\" r=\"11.5\"/><text class=\"pg-t\" x=\"124\" y=\"86.3\" font-size=\"12.08\">1</text></g><g id=\"arcade-b2\" data-btn=\"b2\"><circle class=\"pg-s\" cx=\"152\" cy=\"78\" r=\"11.5\"/><text class=\"pg-t\" x=\"152\" y=\"78.3\" font-size=\"12.08\">2</text></g><g id=\"arcade-b3\" data-btn=\"b3\"><circle class=\"pg-s\" cx=\"181\" cy=\"78\" r=\"11.5\"/><text class=\"pg-t\" x=\"181\" y=\"78.3\" font-size=\"12.08\">3</text></g><g id=\"arcade-b4\" data-btn=\"b4\"><circle class=\"pg-s\" cx=\"120\" cy=\"114\" r=\"11.5\"/><text class=\"pg-t\" x=\"120\" y=\"114.3\" font-size=\"12.08\">4</text></g><g id=\"arcade-b5\" data-btn=\"b5\"><circle class=\"pg-s\" cx=\"148\" cy=\"106\" r=\"11.5\"/><text class=\"pg-t\" x=\"148\" y=\"106.3\" font-size=\"12.08\">5</text></g><g id=\"arcade-b6\" data-btn=\"b6\"><circle class=\"pg-s\" cx=\"177\" cy=\"106\" r=\"11.5\"/><text class=\"pg-t\" x=\"177\" y=\"106.3\" font-size=\"12.08\">6</text></g><g id=\"arcade-b7\" data-btn=\"b7\"><circle class=\"pg-s\" cx=\"210\" cy=\"82\" r=\"11.5\"/></g><g id=\"arcade-b8\" data-btn=\"b8\"><circle class=\"pg-s\" cx=\"206\" cy=\"110\" r=\"11.5\"/></g></svg>",
  "dc": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"dc\" data-name=\"Dreamcast\"><g id=\"dc-l\" data-btn=\"l\"><rect class=\"pg-s\" x=\"31\" y=\"13\" width=\"34\" height=\"8\" rx=\"4\" transform=\"rotate(-16 48 17)\"/><text class=\"pg-t\" x=\"48\" y=\"17.3\" font-size=\"6.24\" transform=\"rotate(-16 48 17)\">L</text></g><g id=\"dc-r\" data-btn=\"r\"><rect class=\"pg-s\" x=\"195\" y=\"13\" width=\"34\" height=\"8\" rx=\"4\" transform=\"rotate(16 212 17)\"/><text class=\"pg-t\" x=\"212\" y=\"17.3\" font-size=\"6.24\" transform=\"rotate(16 212 17)\">R</text></g><path class=\"pg-body\" d=\"M130 6C160 6 182 10 194 20C208 21 228 25 238 40C246 56 245 96 239 124C234 150 228 166 214 166C204 166 198 156 194 140C186 118 166 113 130 113C94 113 74 118 66 140C62 156 56 166 46 166C32 166 26 150 21 124C15 96 14 56 22 40C32 25 52 21 66 20C78 10 100 6 130 6Z\"/><g class=\"pg-d\"><path d=\"M76 34A58 58 0 0 0 184 34\"/><rect x=\"104\" y=\"12\" width=\"52\" height=\"58\" rx=\"7\"/><rect x=\"115\" y=\"30\" width=\"30\" height=\"24\" rx=\"2\"/></g><text class=\"pg-c\" x=\"130\" y=\"21\" font-size=\"5\">VMU</text><g id=\"dc-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"64\" cy=\"42\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"64\" cy=\"42\" r=\"10\"/><circle class=\"pg-kd\" cx=\"64\" cy=\"42\" r=\"5.5\"/></g></g><g id=\"dc-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"67\" y=\"73\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(0 72 76.8)\" d=\"M72 74.6L73.98 78.12L70.02 78.12Z\"/></g><g id=\"dc-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"67\" y=\"93\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(180 72 99.2)\" d=\"M72 97L73.98 100.52L70.02 100.52Z\"/></g><g id=\"dc-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"57\" y=\"83\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(270 60.8 88)\" d=\"M60.8 85.8L62.78 89.32L58.82 89.32Z\"/></g><g id=\"dc-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"77\" y=\"83\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(90 83.2 88)\" d=\"M83.2 85.8L85.18 89.32L81.22 89.32Z\"/></g><path class=\"pg-dpo\" d=\"M67 73H77V83H87V93H77V103H67V93H57V83H67Z\"/><circle class=\"pg-dpc\" cx=\"72\" cy=\"88\" r=\"2.2\"/><g id=\"dc-start\" data-btn=\"start\"><path class=\"pg-s\" stroke-linejoin=\"round\" d=\"M130 92L137.5 104.5H122.5Z\"/></g><text class=\"pg-c\" x=\"130\" y=\"110\" font-size=\"4.6\">START</text><g id=\"dc-y\" data-btn=\"y\" data-c=\"#3aa55a\"><circle class=\"pg-s\" cx=\"196\" cy=\"50\" r=\"7.5\"/><text class=\"pg-t\" x=\"196\" y=\"50.3\" font-size=\"7.88\">Y</text></g><g id=\"dc-b\" data-btn=\"b\" data-c=\"#3b6fd6\"><circle class=\"pg-s\" cx=\"212\" cy=\"65\" r=\"7.5\"/><text class=\"pg-t\" x=\"212\" y=\"65.3\" font-size=\"7.88\">B</text></g><g id=\"dc-a\" data-btn=\"a\" data-c=\"#e0453a\"><circle class=\"pg-s\" cx=\"196\" cy=\"80\" r=\"7.5\"/><text class=\"pg-t\" x=\"196\" y=\"80.3\" font-size=\"7.88\">A</text></g><g id=\"dc-x\" data-btn=\"x\" data-c=\"#e7c33a\"><circle class=\"pg-s\" cx=\"180\" cy=\"65\" r=\"7.5\"/><text class=\"pg-t\" x=\"180\" y=\"65.3\" font-size=\"7.88\">X</text></g></svg>",
  "ds1": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"ds1\" data-name=\"PlayStation DualShock\"><g id=\"ds1-l2\" data-btn=\"l2\"><rect class=\"pg-s\" x=\"46\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"18.3\" font-size=\"6.24\">L2</text></g><g id=\"ds1-r2\" data-btn=\"r2\"><rect class=\"pg-s\" x=\"178\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"18.3\" font-size=\"6.24\">R2</text></g><g id=\"ds1-l1\" data-btn=\"l1\"><rect class=\"pg-s\" x=\"43\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"28.3\" font-size=\"6.24\">L1</text></g><g id=\"ds1-r1\" data-btn=\"r1\"><rect class=\"pg-s\" x=\"175\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"28.3\" font-size=\"6.24\">R1</text></g><path class=\"pg-body\" d=\"M130 38C150 38 166 36 180 34C198 30 224 30 236 50C246 70 248 110 250 140C252 158 240 166 228 164C214 162 206 146 198 130C190 124 186 124 180 127C172 136 150 136 145 125C141 118 137 117 130 117C123 117 119 118 115 125C110 136 88 136 80 127C74 124 70 124 62 130C54 146 46 162 32 164C20 166 8 158 10 140C12 110 14 70 24 50C36 30 62 30 80 34C94 36 110 38 130 38Z\"/><text class=\"pg-c\" x=\"130\" y=\"48\" font-size=\"5.5\">SONY</text><g id=\"ds1-up\" data-btn=\"up\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(0 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(0 64 54.25)\" d=\"M64 51.95L66.07 55.63L61.93 55.63Z\"/></g><g id=\"ds1-right\" data-btn=\"right\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(90 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(90 79.75 70)\" d=\"M79.75 67.7L81.82 71.38L77.68 71.38Z\"/></g><g id=\"ds1-down\" data-btn=\"down\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(180 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(180 64 85.75)\" d=\"M64 83.45L66.07 87.13L61.93 87.13Z\"/></g><g id=\"ds1-left\" data-btn=\"left\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(270 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(270 48.25 70)\" d=\"M48.25 67.7L50.32 71.38L46.18 71.38Z\"/></g><g id=\"ds1-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"106.5\" y=\"61\" width=\"13\" height=\"6\" rx=\"1.5\"/></g><text class=\"pg-c\" x=\"113\" y=\"73\" font-size=\"4.2\">SELECT</text><g id=\"ds1-start\" data-btn=\"start\"><path class=\"pg-s\" stroke-linejoin=\"round\" d=\"M141 60.5H149L154 64L149 67.5H141Z\"/></g><text class=\"pg-c\" x=\"147\" y=\"73\" font-size=\"4.2\">START</text><g id=\"ds1-triangle\" data-btn=\"triangle\" data-c=\"#3ab795\"><circle class=\"pg-s\" cx=\"196\" cy=\"54\" r=\"8\"/><path class=\"pg-y\" d=\"M196 50.22L199.6 56.52L192.4 56.52Z\"/></g><g id=\"ds1-circle\" data-btn=\"circle\" data-c=\"#e2554a\"><circle class=\"pg-s\" cx=\"212\" cy=\"70\" r=\"8\"/><circle class=\"pg-y\" cx=\"212\" cy=\"70\" r=\"3.6\"/></g><g id=\"ds1-cross\" data-btn=\"cross\" data-c=\"#7d9cf0\"><circle class=\"pg-s\" cx=\"196\" cy=\"86\" r=\"8\"/><path class=\"pg-y\" d=\"M192.4 82.4L199.6 89.6M199.6 82.4L192.4 89.6\"/></g><g id=\"ds1-square\" data-btn=\"square\" data-c=\"#e07fbf\"><circle class=\"pg-s\" cx=\"180\" cy=\"70\" r=\"8\"/><rect class=\"pg-y\" x=\"176.94\" y=\"66.94\" width=\"6.12\" height=\"6.12\"/></g><g id=\"ds1-analog\" data-btn=\"analog\"><rect class=\"pg-s\" x=\"125.5\" y=\"83.5\" width=\"9\" height=\"5\" rx=\"1\"/></g><text class=\"pg-c\" x=\"130\" y=\"79\" font-size=\"4\">ANALOG</text><g class=\"pg-d\"><circle cx=\"130\" cy=\"94\" r=\"1.6\"/></g><g id=\"ds1-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"98\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"98\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"98\" cy=\"106\" r=\"5.5\"/></g></g><g id=\"ds1-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"162\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"106\" r=\"5.5\"/></g></g></svg>",
  "gb": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"gb\" data-name=\"Game Boy\"><path class=\"pg-body\" d=\"M90 4H170Q178 4 178 12V138Q178 166 150 166H90Q82 166 82 158V12Q82 4 90 4Z\"/><g class=\"pg-d\"><path d=\"M92 12H168V68Q168 80 156 80H92Z\"/><rect x=\"106\" y=\"20\" width=\"48\" height=\"44\"/><path d=\"M152 154L166 140M157 158L171 144M162 162L174 150\"/></g><text class=\"pg-c\" x=\"130\" y=\"88\" font-size=\"4.6\">Nintendo GAME BOY</text><g id=\"gb-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"98.5\" y=\"98.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(0 103 101.92)\" d=\"M103 99.94L104.78 103.11L101.22 103.11Z\"/></g><g id=\"gb-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"98.5\" y=\"116.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(180 103 122.08)\" d=\"M103 120.1L104.78 123.27L101.22 123.27Z\"/></g><g id=\"gb-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"89.5\" y=\"107.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(270 92.92 112)\" d=\"M92.92 110.02L94.7 113.19L91.14 113.19Z\"/></g><g id=\"gb-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"107.5\" y=\"107.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(90 113.08 112)\" d=\"M113.08 110.02L114.86 113.19L111.3 113.19Z\"/></g><path class=\"pg-dpo\" d=\"M98.5 98.5H107.5V107.5H116.5V116.5H107.5V125.5H98.5V116.5H89.5V107.5H98.5Z\"/><circle class=\"pg-dpc\" cx=\"103\" cy=\"112\" r=\"1.98\"/><g id=\"gb-b\" data-btn=\"b\" data-c=\"#c23a7e\"><circle class=\"pg-s\" cx=\"146\" cy=\"120\" r=\"8\"/></g><g id=\"gb-a\" data-btn=\"a\" data-c=\"#c23a7e\"><circle class=\"pg-s\" cx=\"164\" cy=\"108\" r=\"8\"/></g><text class=\"pg-c\" x=\"146\" y=\"132\" font-size=\"5\">B</text><text class=\"pg-c\" x=\"164\" y=\"120\" font-size=\"5\">A</text><g id=\"gb-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"113.5\" y=\"139.75\" width=\"13\" height=\"4.5\" rx=\"2.25\" transform=\"rotate(-28 120 142)\"/></g><g id=\"gb-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"131.5\" y=\"139.75\" width=\"13\" height=\"4.5\" rx=\"2.25\" transform=\"rotate(-28 138 142)\"/></g><text class=\"pg-c\" x=\"118\" y=\"151\" font-size=\"3.8\">SELECT</text><text class=\"pg-c\" x=\"138\" y=\"151\" font-size=\"3.8\">START</text></svg>",
  "gba": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"gba\" data-name=\"Game Boy Advance\"><g id=\"gba-l\" data-btn=\"l\"><path class=\"pg-s\" d=\"M11.93 46.51A62 62 0 0 1 45.11 27.35L45.94 31.27A58 58 0 0 0 14.9 49.19Z\"/></g><text class=\"pg-c\" x=\"30\" y=\"30\" font-size=\"5.2\">L</text><g id=\"gba-r\" data-btn=\"r\"><path class=\"pg-s\" d=\"M214.89 27.35A62 62 0 0 1 248.07 46.51L245.1 49.19A58 58 0 0 0 214.06 31.27Z\"/></g><text class=\"pg-c\" x=\"230\" y=\"30\" font-size=\"5.2\">R</text><path class=\"pg-body\" d=\"M58 30H202C232 30 248 54 248 88C248 122 232 146 202 146H58C28 146 12 122 12 88C12 54 28 30 58 30Z\"/><g class=\"pg-d\"><rect x=\"72\" y=\"38\" width=\"116\" height=\"96\" rx=\"8\"/><rect x=\"86\" y=\"48\" width=\"88\" height=\"62\"/></g><text class=\"pg-c\" x=\"130\" y=\"122\" font-size=\"4.6\">GAME BOY ADVANCE</text><g id=\"gba-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"39\" y=\"61\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(0 44 64.8)\" d=\"M44 62.6L45.98 66.12L42.02 66.12Z\"/></g><g id=\"gba-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"39\" y=\"81\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(180 44 87.2)\" d=\"M44 85L45.98 88.52L42.02 88.52Z\"/></g><g id=\"gba-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"29\" y=\"71\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(270 32.8 76)\" d=\"M32.8 73.8L34.78 77.32L30.82 77.32Z\"/></g><g id=\"gba-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"49\" y=\"71\" width=\"10\" height=\"10\"/><path class=\"pg-a\" transform=\"rotate(90 55.2 76)\" d=\"M55.2 73.8L57.18 77.32L53.22 77.32Z\"/></g><path class=\"pg-dpo\" d=\"M39 61H49V71H59V81H49V91H39V81H29V71H39Z\"/><circle class=\"pg-dpc\" cx=\"44\" cy=\"76\" r=\"2.2\"/><g id=\"gba-start\" data-btn=\"start\"><circle class=\"pg-s\" cx=\"44\" cy=\"112\" r=\"4\"/></g><g id=\"gba-select\" data-btn=\"select\"><circle class=\"pg-s\" cx=\"44\" cy=\"128\" r=\"4\"/></g><text class=\"pg-c\" x=\"58\" y=\"112\" font-size=\"4\">START</text><text class=\"pg-c\" x=\"59\" y=\"128\" font-size=\"4\">SELECT</text><g id=\"gba-a\" data-btn=\"a\" data-c=\"#a9a4d6\"><circle class=\"pg-s\" cx=\"222\" cy=\"74\" r=\"9\"/><text class=\"pg-t\" x=\"222\" y=\"74.3\" font-size=\"9.45\">A</text></g><g id=\"gba-b\" data-btn=\"b\" data-c=\"#a9a4d6\"><circle class=\"pg-s\" cx=\"202\" cy=\"88\" r=\"9\"/><text class=\"pg-t\" x=\"202\" y=\"88.3\" font-size=\"9.45\">B</text></g></svg>",
  "gbc": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"gbc\" data-name=\"Game Boy Color\"><path class=\"pg-body\" d=\"M96 4H164Q172 4 172 12V124Q172 160 130 166Q88 160 88 124V12Q88 4 96 4Z\"/><g class=\"pg-d\"><rect x=\"94\" y=\"12\" width=\"72\" height=\"66\" rx=\"4\"/><rect x=\"106\" y=\"20\" width=\"48\" height=\"44\"/><path d=\"M150 150L162 138M154 155L166 143\"/></g><text class=\"pg-c\" x=\"130\" y=\"86\" font-size=\"4.6\">GAME BOY COLOR</text><g id=\"gbc-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"101.75\" y=\"95.25\" width=\"8.5\" height=\"8.5\"/><path class=\"pg-a\" transform=\"rotate(0 106 98.48)\" d=\"M106 96.61L107.68 99.6L104.32 99.6Z\"/></g><g id=\"gbc-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"101.75\" y=\"112.25\" width=\"8.5\" height=\"8.5\"/><path class=\"pg-a\" transform=\"rotate(180 106 117.52)\" d=\"M106 115.65L107.68 118.64L104.32 118.64Z\"/></g><g id=\"gbc-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"93.25\" y=\"103.75\" width=\"8.5\" height=\"8.5\"/><path class=\"pg-a\" transform=\"rotate(270 96.48 108)\" d=\"M96.48 106.13L98.16 109.12L94.8 109.12Z\"/></g><g id=\"gbc-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"110.25\" y=\"103.75\" width=\"8.5\" height=\"8.5\"/><path class=\"pg-a\" transform=\"rotate(90 115.52 108)\" d=\"M115.52 106.13L117.2 109.12L113.84 109.12Z\"/></g><path class=\"pg-dpo\" d=\"M101.75 95.25H110.25V103.75H118.75V112.25H110.25V120.75H101.75V112.25H93.25V103.75H101.75Z\"/><circle class=\"pg-dpc\" cx=\"106\" cy=\"108\" r=\"1.87\"/><g id=\"gbc-b\" data-btn=\"b\" data-c=\"#c23a7e\"><circle class=\"pg-s\" cx=\"144\" cy=\"114\" r=\"7.5\"/></g><g id=\"gbc-a\" data-btn=\"a\" data-c=\"#c23a7e\"><circle class=\"pg-s\" cx=\"161\" cy=\"103\" r=\"7.5\"/></g><text class=\"pg-c\" x=\"144\" y=\"125\" font-size=\"5\">B</text><text class=\"pg-c\" x=\"161\" y=\"114\" font-size=\"5\">A</text><g id=\"gbc-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"115.5\" y=\"133.5\" width=\"11\" height=\"5\" rx=\"2.5\"/></g><g id=\"gbc-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"133.5\" y=\"133.5\" width=\"11\" height=\"5\" rx=\"2.5\"/></g><text class=\"pg-c\" x=\"121\" y=\"144\" font-size=\"3.8\">SELECT</text><text class=\"pg-c\" x=\"139\" y=\"144\" font-size=\"3.8\">START</text></svg>",
  "gc": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"gc\" data-name=\"GameCube\"><g id=\"gc-l\" data-btn=\"l\"><rect class=\"pg-s\" x=\"39\" y=\"4\" width=\"38\" height=\"8\" rx=\"4\" transform=\"rotate(-8 58 8)\"/><text class=\"pg-t\" x=\"58\" y=\"8.3\" font-size=\"6.24\" transform=\"rotate(-8 58 8)\">L</text></g><g id=\"gc-r\" data-btn=\"r\"><rect class=\"pg-s\" x=\"183\" y=\"4\" width=\"38\" height=\"8\" rx=\"4\" transform=\"rotate(8 202 8)\"/><text class=\"pg-t\" x=\"202\" y=\"8.3\" font-size=\"6.24\" transform=\"rotate(8 202 8)\">R</text></g><path class=\"pg-body\" d=\"M130 6C168 5 196 8 214 15C238 24 248 46 242 72C238 92 246 122 238 148C234 162 218 167 210 157C202 147 204 130 196 120C188 130 156 132 147 110C142 98 142 76 130 76C118 76 118 98 113 110C104 132 72 130 64 120C56 130 58 147 50 157C42 167 26 162 22 148C14 122 22 92 18 72C12 46 22 24 46 15C64 8 92 5 130 6Z\"/><g id=\"gc-z\" data-btn=\"z\" data-c=\"#8a6cf0\"><rect class=\"pg-s\" x=\"200\" y=\"13\" width=\"24\" height=\"6\" rx=\"3\" transform=\"rotate(10 212 16)\"/><text class=\"pg-t\" x=\"212\" y=\"16.3\" font-size=\"5\" transform=\"rotate(10 212 16)\">Z</text></g><g class=\"pg-d\"><circle cx=\"64\" cy=\"50\" r=\"27\"/><circle cx=\"194\" cy=\"50\" r=\"31\"/></g><g id=\"gc-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"7\"><path class=\"pg-gate\" d=\"M80.63 56.89L70.89 66.63L57.11 66.63L47.37 56.89L47.37 43.11L57.11 33.37L70.89 33.37L80.63 43.11Z\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"64\" cy=\"50\" r=\"11\"/><circle class=\"pg-kd\" cx=\"64\" cy=\"50\" r=\"6.05\"/></g></g><g id=\"gc-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"89.5\" y=\"80.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(0 94 83.92)\" d=\"M94 81.94L95.78 85.11L92.22 85.11Z\"/></g><g id=\"gc-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"89.5\" y=\"98.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(180 94 104.08)\" d=\"M94 102.1L95.78 105.27L92.22 105.27Z\"/></g><g id=\"gc-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"80.5\" y=\"89.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(270 83.92 94)\" d=\"M83.92 92.02L85.7 95.19L82.14 95.19Z\"/></g><g id=\"gc-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"98.5\" y=\"89.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(90 104.08 94)\" d=\"M104.08 92.02L105.86 95.19L102.3 95.19Z\"/></g><path class=\"pg-dpo\" d=\"M89.5 80.5H98.5V89.5H107.5V98.5H98.5V107.5H89.5V98.5H80.5V89.5H89.5Z\"/><circle class=\"pg-dpc\" cx=\"94\" cy=\"94\" r=\"1.98\"/><g id=\"gc-start\" data-btn=\"start\"><circle class=\"pg-s\" cx=\"129\" cy=\"52\" r=\"4.5\"/></g><text class=\"pg-c\" x=\"129\" y=\"43\" font-size=\"4.2\">START/PAUSE</text><g id=\"gc-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\" data-c=\"#f2c230\"><path class=\"pg-gate\" d=\"M176.01 100.97L168.97 108.01L159.03 108.01L151.99 100.97L151.99 91.03L159.03 83.99L168.97 83.99L176.01 91.03Z\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"164\" cy=\"96\" r=\"8\"/><circle class=\"pg-kd\" cx=\"164\" cy=\"96\" r=\"4.4\"/><text class=\"pg-t\" x=\"164\" y=\"96.3\" font-size=\"7.2\">C</text></g></g><g id=\"gc-a\" data-btn=\"a\" data-c=\"#2fae6c\"><circle class=\"pg-s\" cx=\"192\" cy=\"52\" r=\"12\"/><text class=\"pg-t\" x=\"192\" y=\"52.3\" font-size=\"12.6\">A</text></g><g id=\"gc-b\" data-btn=\"b\" data-c=\"#e0453a\"><circle class=\"pg-s\" cx=\"169\" cy=\"66\" r=\"7\"/><text class=\"pg-t\" x=\"169\" y=\"66.3\" font-size=\"7.35\">B</text></g><g id=\"gc-y\" data-btn=\"y\"><path class=\"pg-s\" d=\"M174.91 36.61A23 23 0 0 1 196.78 29.5L195.22 36.84A15.5 15.5 0 0 0 180.48 41.63Z\"/><text class=\"pg-t\" x=\"186.04\" y=\"33.64\" font-size=\"5.5\">Y</text></g><g id=\"gc-x\" data-btn=\"x\"><path class=\"pg-s\" d=\"M209.62 37.22A23 23 0 0 1 214.32 57.56L207.04 55.75A15.5 15.5 0 0 0 203.87 42.04Z\"/><text class=\"pg-t\" x=\"210.81\" y=\"47.66\" font-size=\"5.5\">X</text></g></svg>",
  "md3": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"md3\" data-name=\"Mega Drive / Genesis (3-button)\"><path class=\"pg-body\" d=\"M130 30C180 27 230 28 244 60C256 92 246 136 216 148C190 156 172 122 130 120C88 122 70 156 44 148C14 136 4 92 16 60C30 28 80 27 130 30Z\"/><g class=\"pg-d\"><circle cx=\"70\" cy=\"76\" r=\"30\"/></g><g id=\"md3-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"63.5\" y=\"56.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(0 70 61.44)\" d=\"M70 58.58L72.57 63.16L67.43 63.16Z\"/></g><g id=\"md3-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"63.5\" y=\"82.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(180 70 90.56)\" d=\"M70 87.7L72.57 92.28L67.43 92.28Z\"/></g><g id=\"md3-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"50.5\" y=\"69.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(270 55.44 76)\" d=\"M55.44 73.14L58.01 77.72L52.87 77.72Z\"/></g><g id=\"md3-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"76.5\" y=\"69.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(90 84.56 76)\" d=\"M84.56 73.14L87.13 77.72L81.99 77.72Z\"/></g><path class=\"pg-dpo\" d=\"M63.5 56.5H76.5V69.5H89.5V82.5H76.5V95.5H63.5V82.5H50.5V69.5H63.5Z\"/><circle class=\"pg-dpc\" cx=\"70\" cy=\"76\" r=\"2.86\"/><text class=\"pg-c\" x=\"132\" y=\"52\" font-size=\"6.5\">SEGA</text><g id=\"md3-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"174\" y=\"47.5\" width=\"24\" height=\"9\" rx=\"4.5\"/></g><text class=\"pg-c\" x=\"186\" y=\"43\" font-size=\"4.6\">START</text><g class=\"pg-d\"><path d=\"M150 96C160 80 220 66 236 80C246 92 230 110 214 112C196 116 168 120 156 114C148 110 147 102 150 96Z\"/></g><g id=\"md3-a\" data-btn=\"a\"><circle class=\"pg-s\" cx=\"166\" cy=\"101\" r=\"10.5\"/><text class=\"pg-t\" x=\"166\" y=\"101.3\" font-size=\"11.03\">A</text></g><g id=\"md3-b\" data-btn=\"b\"><circle class=\"pg-s\" cx=\"192\" cy=\"94\" r=\"10.5\"/><text class=\"pg-t\" x=\"192\" y=\"94.3\" font-size=\"11.03\">B</text></g><g id=\"md3-c\" data-btn=\"c\"><circle class=\"pg-s\" cx=\"218\" cy=\"87\" r=\"10.5\"/><text class=\"pg-t\" x=\"218\" y=\"87.3\" font-size=\"11.03\">C</text></g></svg>",
  "md6": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"md6\" data-name=\"Mega Drive / Genesis (6-button)\"><g id=\"md6-mode\" data-btn=\"mode\"><rect class=\"pg-s\" x=\"204\" y=\"28\" width=\"20\" height=\"6\" rx=\"3\" transform=\"rotate(24 214 31)\"/></g><text class=\"pg-c\" x=\"222\" y=\"22\" font-size=\"4.4\">MODE</text><path class=\"pg-body\" d=\"M130 34C172 30 224 22 242 56C256 86 248 136 214 146C190 152 176 126 130 124C84 126 70 152 46 146C12 136 4 86 18 56C36 22 88 30 130 34Z\"/><text class=\"pg-c\" x=\"130\" y=\"50\" font-size=\"6.5\">SEGA</text><g class=\"pg-d\"><circle cx=\"68\" cy=\"82\" r=\"28\"/></g><g id=\"md6-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"62\" y=\"64\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(0 68 68.56)\" d=\"M68 65.92L70.38 70.14L65.62 70.14Z\"/></g><g id=\"md6-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"62\" y=\"88\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(180 68 95.44)\" d=\"M68 92.8L70.38 97.02L65.62 97.02Z\"/></g><g id=\"md6-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"50\" y=\"76\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(270 54.56 82)\" d=\"M54.56 79.36L56.94 83.58L52.18 83.58Z\"/></g><g id=\"md6-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"74\" y=\"76\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(90 81.44 82)\" d=\"M81.44 79.36L83.82 83.58L79.06 83.58Z\"/></g><path class=\"pg-dpo\" d=\"M62 64H74V76H86V88H74V100H62V88H50V76H62Z\"/><circle class=\"pg-dpc\" cx=\"68\" cy=\"82\" r=\"2.64\"/><g id=\"md6-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"122\" y=\"80.5\" width=\"16\" height=\"7\" rx=\"3.5\"/></g><text class=\"pg-c\" x=\"130\" y=\"94\" font-size=\"4.6\">START</text><g id=\"md6-x\" data-btn=\"x\"><circle class=\"pg-s\" cx=\"160\" cy=\"80\" r=\"7.5\"/><text class=\"pg-t\" x=\"160\" y=\"80.3\" font-size=\"7.88\">X</text></g><g id=\"md6-y\" data-btn=\"y\"><circle class=\"pg-s\" cx=\"182\" cy=\"72\" r=\"7.5\"/><text class=\"pg-t\" x=\"182\" y=\"72.3\" font-size=\"7.88\">Y</text></g><g id=\"md6-z\" data-btn=\"z\"><circle class=\"pg-s\" cx=\"204\" cy=\"66\" r=\"7.5\"/><text class=\"pg-t\" x=\"204\" y=\"66.3\" font-size=\"7.88\">Z</text></g><g id=\"md6-a\" data-btn=\"a\"><circle class=\"pg-s\" cx=\"166\" cy=\"106\" r=\"9.5\"/><text class=\"pg-t\" x=\"166\" y=\"106.3\" font-size=\"9.97\">A</text></g><g id=\"md6-b\" data-btn=\"b\"><circle class=\"pg-s\" cx=\"190\" cy=\"98\" r=\"9.5\"/><text class=\"pg-t\" x=\"190\" y=\"98.3\" font-size=\"9.97\">B</text></g><g id=\"md6-c\" data-btn=\"c\"><circle class=\"pg-s\" cx=\"214\" cy=\"91\" r=\"9.5\"/><text class=\"pg-t\" x=\"214\" y=\"91.3\" font-size=\"9.97\">C</text></g></svg>",
  "n64": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"n64\" data-name=\"Nintendo 64\"><g id=\"n64-l\" data-btn=\"l\"><rect class=\"pg-s\" x=\"32\" y=\"20.5\" width=\"36\" height=\"7\" rx=\"3.5\" transform=\"rotate(-16 50 24)\"/><text class=\"pg-t\" x=\"50\" y=\"24.3\" font-size=\"5.46\" transform=\"rotate(-16 50 24)\">L</text></g><g id=\"n64-r\" data-btn=\"r\"><rect class=\"pg-s\" x=\"192\" y=\"20.5\" width=\"36\" height=\"7\" rx=\"3.5\" transform=\"rotate(16 210 24)\"/><text class=\"pg-t\" x=\"210\" y=\"24.3\" font-size=\"5.46\" transform=\"rotate(16 210 24)\">R</text></g><path class=\"pg-body\" d=\"M130 6C150 6 166 8 176 16C190 22 230 22 244 42C256 60 252 92 244 120C238 146 236 166 220 166C206 166 200 150 198 132C196 112 186 98 172 98C160 98 156 112 152 130C148 152 146 168 130 168C114 168 112 152 108 130C104 112 100 98 88 98C74 98 64 112 62 132C60 150 54 166 40 166C24 166 22 146 16 120C8 92 4 60 16 42C30 22 70 22 84 16C94 8 110 6 130 6Z\"/><text class=\"pg-c\" x=\"130\" y=\"18\" font-size=\"6\">Nintendo</text><g class=\"pg-d\"><circle cx=\"60\" cy=\"54\" r=\"23\"/></g><g id=\"n64-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"54.5\" y=\"37.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(0 60 41.68)\" d=\"M60 39.26L62.18 43.13L57.82 43.13Z\"/></g><g id=\"n64-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"54.5\" y=\"59.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(180 60 66.32)\" d=\"M60 63.9L62.18 67.77L57.82 67.77Z\"/></g><g id=\"n64-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"43.5\" y=\"48.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(270 47.68 54)\" d=\"M47.68 51.58L49.86 55.45L45.5 55.45Z\"/></g><g id=\"n64-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"65.5\" y=\"48.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(90 72.32 54)\" d=\"M72.32 51.58L74.5 55.45L70.14 55.45Z\"/></g><path class=\"pg-dpo\" d=\"M54.5 37.5H65.5V48.5H76.5V59.5H65.5V70.5H54.5V59.5H43.5V48.5H54.5Z\"/><circle class=\"pg-dpc\" cx=\"60\" cy=\"54\" r=\"2.42\"/><g id=\"n64-start\" data-btn=\"start\" data-c=\"#d8453a\"><circle class=\"pg-s\" cx=\"130\" cy=\"52\" r=\"6.5\"/></g><text class=\"pg-c\" x=\"130\" y=\"41\" font-size=\"4.6\">START</text><g id=\"n64-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"6\"><path class=\"pg-gate\" d=\"M143.86 93.74L135.74 101.86L124.26 101.86L116.14 93.74L116.14 82.26L124.26 74.14L135.74 74.14L143.86 82.26Z\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"130\" cy=\"88\" r=\"9\"/><circle class=\"pg-kd\" cx=\"130\" cy=\"88\" r=\"4.95\"/></g></g><g id=\"n64-z\" data-btn=\"z\"><rect class=\"pg-s\" x=\"122\" y=\"141\" width=\"16\" height=\"10\" rx=\"3\"/><text class=\"pg-t\" x=\"130\" y=\"146.3\" font-size=\"7.5\">Z</text></g><text class=\"pg-c\" x=\"130\" y=\"158\" font-size=\"4\">(back)</text><g id=\"n64-b\" data-btn=\"b\" data-c=\"#2e9e57\"><circle class=\"pg-s\" cx=\"172\" cy=\"58\" r=\"9\"/><text class=\"pg-t\" x=\"172\" y=\"58.3\" font-size=\"9.45\">B</text></g><g id=\"n64-a\" data-btn=\"a\" data-c=\"#3d6fe0\"><circle class=\"pg-s\" cx=\"182\" cy=\"80\" r=\"9\"/><text class=\"pg-t\" x=\"182\" y=\"80.3\" font-size=\"9.45\">A</text></g><g id=\"n64-cup\" data-btn=\"cup\" data-c=\"#f2c230\"><circle class=\"pg-s\" cx=\"213\" cy=\"49\" r=\"6.2\"/><path class=\"pg-a\" transform=\"rotate(0 213 49)\" d=\"M213 45.9L215.79 50.86L210.21 50.86Z\"/></g><g id=\"n64-cright\" data-btn=\"cright\" data-c=\"#f2c230\"><circle class=\"pg-s\" cx=\"225\" cy=\"61\" r=\"6.2\"/><path class=\"pg-a\" transform=\"rotate(90 225 61)\" d=\"M225 57.9L227.79 62.86L222.21 62.86Z\"/></g><g id=\"n64-cdown\" data-btn=\"cdown\" data-c=\"#f2c230\"><circle class=\"pg-s\" cx=\"213\" cy=\"73\" r=\"6.2\"/><path class=\"pg-a\" transform=\"rotate(180 213 73)\" d=\"M213 69.9L215.79 74.86L210.21 74.86Z\"/></g><g id=\"n64-cleft\" data-btn=\"cleft\" data-c=\"#f2c230\"><circle class=\"pg-s\" cx=\"201\" cy=\"61\" r=\"6.2\"/><path class=\"pg-a\" transform=\"rotate(270 201 61)\" d=\"M201 57.9L203.79 62.86L198.21 62.86Z\"/></g></svg>",
  "nes": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"nes\" data-name=\"NES\"><path class=\"pg-body\" d=\"M24 40H236Q242 40 242 46V130Q242 136 236 136H24Q18 136 18 130V46Q18 40 24 40Z\"/><g class=\"pg-d\"><rect x=\"26\" y=\"50\" width=\"208\" height=\"78\" rx=\"3\"/><rect x=\"98\" y=\"58\" width=\"64\" height=\"8\" rx=\"2\"/><rect x=\"98\" y=\"70\" width=\"64\" height=\"8\" rx=\"2\"/><rect x=\"98\" y=\"82\" width=\"64\" height=\"8\" rx=\"2\"/><rect x=\"98\" y=\"96\" width=\"64\" height=\"26\" rx=\"3\"/><rect x=\"170\" y=\"94\" width=\"28\" height=\"28\" rx=\"2\"/><rect x=\"204\" y=\"94\" width=\"28\" height=\"28\" rx=\"2\"/></g><text class=\"pg-c pg-cr\" x=\"214\" y=\"61\" font-size=\"6.5\">Nintendo</text><g id=\"nes-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"53\" y=\"73\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(0 60 78.32)\" d=\"M60 75.24L62.77 80.17L57.23 80.17Z\"/></g><g id=\"nes-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"53\" y=\"101\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(180 60 109.68)\" d=\"M60 106.6L62.77 111.53L57.23 111.53Z\"/></g><g id=\"nes-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"39\" y=\"87\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(270 44.32 94)\" d=\"M44.32 90.92L47.09 95.85L41.55 95.85Z\"/></g><g id=\"nes-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"67\" y=\"87\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(90 75.68 94)\" d=\"M75.68 90.92L78.45 95.85L72.91 95.85Z\"/></g><path class=\"pg-dpo\" d=\"M53 73H67V87H81V101H67V115H53V101H39V87H53Z\"/><circle class=\"pg-dpc\" cx=\"60\" cy=\"94\" r=\"3.08\"/><text class=\"pg-c pg-cr\" x=\"116\" y=\"92\" font-size=\"4.6\">SELECT</text><text class=\"pg-c pg-cr\" x=\"144\" y=\"92\" font-size=\"4.6\">START</text><g id=\"nes-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"107\" y=\"104.5\" width=\"18\" height=\"7\" rx=\"3.5\"/></g><g id=\"nes-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"135\" y=\"104.5\" width=\"18\" height=\"7\" rx=\"3.5\"/></g><g id=\"nes-b\" data-btn=\"b\" data-c=\"#d8333a\"><circle class=\"pg-s\" cx=\"184\" cy=\"108\" r=\"10.5\"/><text class=\"pg-t\" x=\"184\" y=\"108.3\" font-size=\"0.01\">B</text></g><g id=\"nes-a\" data-btn=\"a\" data-c=\"#d8333a\"><circle class=\"pg-s\" cx=\"218\" cy=\"108\" r=\"10.5\"/><text class=\"pg-t\" x=\"218\" y=\"108.3\" font-size=\"0.01\">A</text></g><text class=\"pg-c pg-cr\" x=\"196\" y=\"89\" font-size=\"5.5\">B</text><text class=\"pg-c pg-cr\" x=\"230\" y=\"89\" font-size=\"5.5\">A</text></svg>",
  "ps1": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"ps1\" data-name=\"PlayStation (digital)\"><g id=\"ps1-l2\" data-btn=\"l2\"><rect class=\"pg-s\" x=\"46\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"18.3\" font-size=\"6.24\">L2</text></g><g id=\"ps1-r2\" data-btn=\"r2\"><rect class=\"pg-s\" x=\"178\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"18.3\" font-size=\"6.24\">R2</text></g><g id=\"ps1-l1\" data-btn=\"l1\"><rect class=\"pg-s\" x=\"43\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"28.3\" font-size=\"6.24\">L1</text></g><g id=\"ps1-r1\" data-btn=\"r1\"><rect class=\"pg-s\" x=\"175\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"28.3\" font-size=\"6.24\">R1</text></g><path class=\"pg-body\" d=\"M130 38C150 38 166 36 180 34C198 30 224 30 236 50C246 70 248 110 250 140C252 158 240 166 228 164C214 162 206 146 198 130C190 120 180 114 166 114C150 114 140 114 130 114C120 114 110 114 94 114C80 114 70 120 62 130C54 146 46 162 32 164C20 166 8 158 10 140C12 110 14 70 24 50C36 30 62 30 80 34C94 36 110 38 130 38Z\"/><text class=\"pg-c\" x=\"130\" y=\"50\" font-size=\"5.5\">SONY</text><g id=\"ps1-up\" data-btn=\"up\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(0 64 72)\" d=\"M64 68.7L69.75 64.5V51Q69.75 49.5 68.25 49.5H59.75Q58.25 49.5 58.25 51V64.5Z\"/><path class=\"pg-a\" transform=\"rotate(0 64 56.25)\" d=\"M64 53.95L66.07 57.63L61.93 57.63Z\"/></g><g id=\"ps1-right\" data-btn=\"right\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(90 64 72)\" d=\"M64 68.7L69.75 64.5V51Q69.75 49.5 68.25 49.5H59.75Q58.25 49.5 58.25 51V64.5Z\"/><path class=\"pg-a\" transform=\"rotate(90 79.75 72)\" d=\"M79.75 69.7L81.82 73.38L77.68 73.38Z\"/></g><g id=\"ps1-down\" data-btn=\"down\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(180 64 72)\" d=\"M64 68.7L69.75 64.5V51Q69.75 49.5 68.25 49.5H59.75Q58.25 49.5 58.25 51V64.5Z\"/><path class=\"pg-a\" transform=\"rotate(180 64 87.75)\" d=\"M64 85.45L66.07 89.13L61.93 89.13Z\"/></g><g id=\"ps1-left\" data-btn=\"left\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(270 64 72)\" d=\"M64 68.7L69.75 64.5V51Q69.75 49.5 68.25 49.5H59.75Q58.25 49.5 58.25 51V64.5Z\"/><path class=\"pg-a\" transform=\"rotate(270 48.25 72)\" d=\"M48.25 69.7L50.32 73.38L46.18 73.38Z\"/></g><g id=\"ps1-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"106.5\" y=\"67\" width=\"13\" height=\"6\" rx=\"1.5\"/></g><text class=\"pg-c\" x=\"113\" y=\"79\" font-size=\"4.2\">SELECT</text><g id=\"ps1-start\" data-btn=\"start\"><path class=\"pg-s\" stroke-linejoin=\"round\" d=\"M141 66.5H149L154 70L149 73.5H141Z\"/></g><text class=\"pg-c\" x=\"147\" y=\"79\" font-size=\"4.2\">START</text><g id=\"ps1-triangle\" data-btn=\"triangle\" data-c=\"#3ab795\"><circle class=\"pg-s\" cx=\"196\" cy=\"56\" r=\"8\"/><path class=\"pg-y\" d=\"M196 52.22L199.6 58.52L192.4 58.52Z\"/></g><g id=\"ps1-circle\" data-btn=\"circle\" data-c=\"#e2554a\"><circle class=\"pg-s\" cx=\"212\" cy=\"72\" r=\"8\"/><circle class=\"pg-y\" cx=\"212\" cy=\"72\" r=\"3.6\"/></g><g id=\"ps1-cross\" data-btn=\"cross\" data-c=\"#7d9cf0\"><circle class=\"pg-s\" cx=\"196\" cy=\"88\" r=\"8\"/><path class=\"pg-y\" d=\"M192.4 84.4L199.6 91.6M199.6 84.4L192.4 91.6\"/></g><g id=\"ps1-square\" data-btn=\"square\" data-c=\"#e07fbf\"><circle class=\"pg-s\" cx=\"180\" cy=\"72\" r=\"8\"/><rect class=\"pg-y\" x=\"176.94\" y=\"68.94\" width=\"6.12\" height=\"6.12\"/></g></svg>",
  "ps2": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"ps2\" data-name=\"PlayStation 2 DualShock 2\"><g id=\"ps2-l2\" data-btn=\"l2\"><rect class=\"pg-s\" x=\"46\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"18.3\" font-size=\"6.24\">L2</text></g><g id=\"ps2-r2\" data-btn=\"r2\"><rect class=\"pg-s\" x=\"178\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"18.3\" font-size=\"6.24\">R2</text></g><g id=\"ps2-l1\" data-btn=\"l1\"><rect class=\"pg-s\" x=\"43\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"28.3\" font-size=\"6.24\">L1</text></g><g id=\"ps2-r1\" data-btn=\"r1\"><rect class=\"pg-s\" x=\"175\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"28.3\" font-size=\"6.24\">R1</text></g><path class=\"pg-body\" d=\"M130 38C150 38 166 36 180 34C198 30 224 30 236 50C246 70 248 110 250 140C252 158 240 166 228 164C214 162 206 146 198 130C190 124 186 124 180 127C172 136 150 136 145 125C141 118 137 117 130 117C123 117 119 118 115 125C110 136 88 136 80 127C74 124 70 124 62 130C54 146 46 162 32 164C20 166 8 158 10 140C12 110 14 70 24 50C36 30 62 30 80 34C94 36 110 38 130 38Z\"/><text class=\"pg-c\" x=\"130\" y=\"48\" font-size=\"4.6\">DUALSHOCK 2</text><g id=\"ps2-up\" data-btn=\"up\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(0 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(0 64 54.25)\" d=\"M64 51.95L66.07 55.63L61.93 55.63Z\"/></g><g id=\"ps2-right\" data-btn=\"right\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(90 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(90 79.75 70)\" d=\"M79.75 67.7L81.82 71.38L77.68 71.38Z\"/></g><g id=\"ps2-down\" data-btn=\"down\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(180 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(180 64 85.75)\" d=\"M64 83.45L66.07 87.13L61.93 87.13Z\"/></g><g id=\"ps2-left\" data-btn=\"left\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(270 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(270 48.25 70)\" d=\"M48.25 67.7L50.32 71.38L46.18 71.38Z\"/></g><g id=\"ps2-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"106.5\" y=\"61\" width=\"13\" height=\"6\" rx=\"1.5\"/></g><text class=\"pg-c\" x=\"113\" y=\"73\" font-size=\"4.2\">SELECT</text><g id=\"ps2-start\" data-btn=\"start\"><path class=\"pg-s\" stroke-linejoin=\"round\" d=\"M141 60.5H149L154 64L149 67.5H141Z\"/></g><text class=\"pg-c\" x=\"147\" y=\"73\" font-size=\"4.2\">START</text><g id=\"ps2-triangle\" data-btn=\"triangle\" data-c=\"#3ab795\"><circle class=\"pg-s\" cx=\"196\" cy=\"54\" r=\"8\"/><path class=\"pg-y\" d=\"M196 50.22L199.6 56.52L192.4 56.52Z\"/></g><g id=\"ps2-circle\" data-btn=\"circle\" data-c=\"#e2554a\"><circle class=\"pg-s\" cx=\"212\" cy=\"70\" r=\"8\"/><circle class=\"pg-y\" cx=\"212\" cy=\"70\" r=\"3.6\"/></g><g id=\"ps2-cross\" data-btn=\"cross\" data-c=\"#7d9cf0\"><circle class=\"pg-s\" cx=\"196\" cy=\"86\" r=\"8\"/><path class=\"pg-y\" d=\"M192.4 82.4L199.6 89.6M199.6 82.4L192.4 89.6\"/></g><g id=\"ps2-square\" data-btn=\"square\" data-c=\"#e07fbf\"><circle class=\"pg-s\" cx=\"180\" cy=\"70\" r=\"8\"/><rect class=\"pg-y\" x=\"176.94\" y=\"66.94\" width=\"6.12\" height=\"6.12\"/></g><g id=\"ps2-analog\" data-btn=\"analog\"><rect class=\"pg-s\" x=\"125.5\" y=\"83.5\" width=\"9\" height=\"5\" rx=\"1\"/></g><text class=\"pg-c\" x=\"130\" y=\"79\" font-size=\"4\">ANALOG</text><g class=\"pg-d\"><circle cx=\"130\" cy=\"94\" r=\"1.6\"/></g><g id=\"ps2-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"98\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"98\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"98\" cy=\"106\" r=\"5.5\"/></g></g><g id=\"ps2-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"162\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"106\" r=\"5.5\"/></g></g></svg>",
  "ps3": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"ps3\" data-name=\"PlayStation 3 DualShock 3\"><g id=\"ps3-l2\" data-btn=\"l2\"><rect class=\"pg-s\" x=\"46\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"18.3\" font-size=\"6.24\">L2</text></g><g id=\"ps3-r2\" data-btn=\"r2\"><rect class=\"pg-s\" x=\"178\" y=\"14\" width=\"36\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"18.3\" font-size=\"6.24\">R2</text></g><g id=\"ps3-l1\" data-btn=\"l1\"><rect class=\"pg-s\" x=\"43\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"64\" y=\"28.3\" font-size=\"6.24\">L1</text></g><g id=\"ps3-r1\" data-btn=\"r1\"><rect class=\"pg-s\" x=\"175\" y=\"24\" width=\"42\" height=\"8\" rx=\"4\"/><text class=\"pg-t\" x=\"196\" y=\"28.3\" font-size=\"6.24\">R1</text></g><path class=\"pg-body\" d=\"M130 38C150 38 166 36 180 34C198 30 224 30 236 50C246 70 248 110 250 140C252 158 240 166 228 164C214 162 206 146 198 130C190 124 186 124 180 127C172 136 150 136 145 125C141 118 137 117 130 117C123 117 119 118 115 125C110 136 88 136 80 127C74 124 70 124 62 130C54 146 46 162 32 164C20 166 8 158 10 140C12 110 14 70 24 50C36 30 62 30 80 34C94 36 110 38 130 38Z\"/><g class=\"pg-d\"><circle cx=\"118\" cy=\"38\" r=\"1.3\"/><circle cx=\"126\" cy=\"38\" r=\"1.3\"/><circle cx=\"134\" cy=\"38\" r=\"1.3\"/><circle cx=\"142\" cy=\"38\" r=\"1.3\"/></g><text class=\"pg-c\" x=\"130\" y=\"48\" font-size=\"4.6\">DUALSHOCK 3</text><g id=\"ps3-up\" data-btn=\"up\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(0 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(0 64 54.25)\" d=\"M64 51.95L66.07 55.63L61.93 55.63Z\"/></g><g id=\"ps3-right\" data-btn=\"right\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(90 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(90 79.75 70)\" d=\"M79.75 67.7L81.82 71.38L77.68 71.38Z\"/></g><g id=\"ps3-down\" data-btn=\"down\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(180 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(180 64 85.75)\" d=\"M64 83.45L66.07 87.13L61.93 87.13Z\"/></g><g id=\"ps3-left\" data-btn=\"left\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(270 64 70)\" d=\"M64 66.7L69.75 62.5V49Q69.75 47.5 68.25 47.5H59.75Q58.25 47.5 58.25 49V62.5Z\"/><path class=\"pg-a\" transform=\"rotate(270 48.25 70)\" d=\"M48.25 67.7L50.32 71.38L46.18 71.38Z\"/></g><g id=\"ps3-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"106.5\" y=\"61\" width=\"13\" height=\"6\" rx=\"1.5\"/></g><text class=\"pg-c\" x=\"113\" y=\"73\" font-size=\"4.2\">SELECT</text><g id=\"ps3-start\" data-btn=\"start\"><path class=\"pg-s\" stroke-linejoin=\"round\" d=\"M141 60.5H149L154 64L149 67.5H141Z\"/></g><text class=\"pg-c\" x=\"147\" y=\"73\" font-size=\"4.2\">START</text><g id=\"ps3-triangle\" data-btn=\"triangle\" data-c=\"#3ab795\"><circle class=\"pg-s\" cx=\"196\" cy=\"54\" r=\"8\"/><path class=\"pg-y\" d=\"M196 50.22L199.6 56.52L192.4 56.52Z\"/></g><g id=\"ps3-circle\" data-btn=\"circle\" data-c=\"#e2554a\"><circle class=\"pg-s\" cx=\"212\" cy=\"70\" r=\"8\"/><circle class=\"pg-y\" cx=\"212\" cy=\"70\" r=\"3.6\"/></g><g id=\"ps3-cross\" data-btn=\"cross\" data-c=\"#7d9cf0\"><circle class=\"pg-s\" cx=\"196\" cy=\"86\" r=\"8\"/><path class=\"pg-y\" d=\"M192.4 82.4L199.6 89.6M199.6 82.4L192.4 89.6\"/></g><g id=\"ps3-square\" data-btn=\"square\" data-c=\"#e07fbf\"><circle class=\"pg-s\" cx=\"180\" cy=\"70\" r=\"8\"/><rect class=\"pg-y\" x=\"176.94\" y=\"66.94\" width=\"6.12\" height=\"6.12\"/></g><g id=\"ps3-ps\" data-btn=\"ps\"><circle class=\"pg-s\" cx=\"130\" cy=\"88\" r=\"6\"/><text class=\"pg-t\" x=\"130\" y=\"88.3\" font-size=\"4.4\">PS</text></g><g id=\"ps3-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"98\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"98\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"98\" cy=\"106\" r=\"5.5\"/></g></g><g id=\"ps3-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"162\" cy=\"106\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"106\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"106\" r=\"5.5\"/></g></g></svg>",
  "psp": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"psp\" data-name=\"PSP\"><g id=\"psp-l\" data-btn=\"l\"><path class=\"pg-s\" d=\"M14.9 49.19A58 58 0 0 1 45.94 31.27L46.77 35.18A54 54 0 0 0 17.87 51.87Z\"/></g><text class=\"pg-c\" x=\"30\" y=\"32\" font-size=\"5.2\">L</text><g id=\"psp-r\" data-btn=\"r\"><path class=\"pg-s\" d=\"M214.06 31.27A58 58 0 0 1 245.1 49.19L242.13 51.87A54 54 0 0 0 213.23 35.18Z\"/></g><text class=\"pg-c\" x=\"230\" y=\"32\" font-size=\"5.2\">R</text><path class=\"pg-body\" d=\"M58 34H202C232 34 254 58 254 88C254 118 232 142 202 142H58C28 142 6 118 6 88C6 58 28 34 58 34Z\"/><g class=\"pg-d\"><rect x=\"62\" y=\"44\" width=\"136\" height=\"78\" rx=\"2\"/></g><text class=\"pg-c\" x=\"130\" y=\"83\" font-size=\"9\">PSP</text><g id=\"psp-up\" data-btn=\"up\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(0 34 70)\" d=\"M34 67.8L38 65V56.5Q38 55 36.5 55H31.5Q30 55 30 56.5V65Z\"/><path class=\"pg-a\" transform=\"rotate(0 34 59.5)\" d=\"M34 57.9L35.44 60.46L32.56 60.46Z\"/></g><g id=\"psp-right\" data-btn=\"right\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(90 34 70)\" d=\"M34 67.8L38 65V56.5Q38 55 36.5 55H31.5Q30 55 30 56.5V65Z\"/><path class=\"pg-a\" transform=\"rotate(90 44.5 70)\" d=\"M44.5 68.4L45.94 70.96L43.06 70.96Z\"/></g><g id=\"psp-down\" data-btn=\"down\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(180 34 70)\" d=\"M34 67.8L38 65V56.5Q38 55 36.5 55H31.5Q30 55 30 56.5V65Z\"/><path class=\"pg-a\" transform=\"rotate(180 34 80.5)\" d=\"M34 78.9L35.44 81.46L32.56 81.46Z\"/></g><g id=\"psp-left\" data-btn=\"left\" class=\"pg-dk\"><path class=\"pg-s\" transform=\"rotate(270 34 70)\" d=\"M34 67.8L38 65V56.5Q38 55 36.5 55H31.5Q30 55 30 56.5V65Z\"/><path class=\"pg-a\" transform=\"rotate(270 23.5 70)\" d=\"M23.5 68.4L24.94 70.96L22.06 70.96Z\"/></g><g id=\"psp-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"2.5\"><circle class=\"pg-gate\" cx=\"34\" cy=\"108\" r=\"9\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"34\" cy=\"108\" r=\"6.5\"/><circle class=\"pg-kd\" cx=\"34\" cy=\"108\" r=\"3.58\"/></g></g><g id=\"psp-triangle\" data-btn=\"triangle\"><circle class=\"pg-s\" cx=\"228\" cy=\"70\" r=\"6\"/><path class=\"pg-y\" d=\"M228 67.17L230.7 71.89L225.3 71.89Z\"/></g><g id=\"psp-circle\" data-btn=\"circle\"><circle class=\"pg-s\" cx=\"240\" cy=\"82\" r=\"6\"/><circle class=\"pg-y\" cx=\"240\" cy=\"82\" r=\"2.7\"/></g><g id=\"psp-cross\" data-btn=\"cross\"><circle class=\"pg-s\" cx=\"228\" cy=\"94\" r=\"6\"/><path class=\"pg-y\" d=\"M225.3 91.3L230.7 96.7M230.7 91.3L225.3 96.7\"/></g><g id=\"psp-square\" data-btn=\"square\"><circle class=\"pg-s\" cx=\"216\" cy=\"82\" r=\"6\"/><rect class=\"pg-y\" x=\"213.71\" y=\"79.7\" width=\"4.59\" height=\"4.59\"/></g><g id=\"psp-home\" data-btn=\"home\"><rect class=\"pg-s\" x=\"66\" y=\"129\" width=\"16\" height=\"6\" rx=\"3\"/><text class=\"pg-t\" x=\"74\" y=\"132.3\" font-size=\"3.6\">HOME</text></g><g id=\"psp-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"170\" y=\"129\" width=\"16\" height=\"6\" rx=\"3\"/><text class=\"pg-t\" x=\"178\" y=\"132.3\" font-size=\"3.4\">SELECT</text></g><g id=\"psp-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"190\" y=\"129\" width=\"16\" height=\"6\" rx=\"3\"/><text class=\"pg-t\" x=\"198\" y=\"132.3\" font-size=\"3.6\">START</text></g></svg>",
  "saturn": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"saturn\" data-name=\"Sega Saturn\"><g id=\"saturn-l\" data-btn=\"l\"><rect class=\"pg-s\" x=\"36\" y=\"23\" width=\"44\" height=\"8\" rx=\"4\" transform=\"rotate(-16 58 27)\"/><text class=\"pg-t\" x=\"58\" y=\"27.3\" font-size=\"6.24\" transform=\"rotate(-16 58 27)\">L</text></g><g id=\"saturn-r\" data-btn=\"r\"><rect class=\"pg-s\" x=\"180\" y=\"23\" width=\"44\" height=\"8\" rx=\"4\" transform=\"rotate(16 202 27)\"/><text class=\"pg-t\" x=\"202\" y=\"27.3\" font-size=\"6.24\" transform=\"rotate(16 202 27)\">R</text></g><path class=\"pg-body\" d=\"M130 30C166 27 206 20 232 36C252 50 254 108 238 134C224 154 192 152 172 140C160 133 147 129 130 129C113 129 100 133 88 140C68 152 36 154 22 134C6 108 8 50 28 36C54 20 94 27 130 30Z\"/><text class=\"pg-c\" x=\"130\" y=\"48\" font-size=\"5.2\">SEGA SATURN</text><g class=\"pg-d\"><circle cx=\"68\" cy=\"80\" r=\"26\"/></g><g id=\"saturn-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"62\" y=\"62\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(0 68 66.56)\" d=\"M68 63.92L70.38 68.14L65.62 68.14Z\"/></g><g id=\"saturn-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"62\" y=\"86\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(180 68 93.44)\" d=\"M68 90.8L70.38 95.02L65.62 95.02Z\"/></g><g id=\"saturn-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"50\" y=\"74\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(270 54.56 80)\" d=\"M54.56 77.36L56.94 81.58L52.18 81.58Z\"/></g><g id=\"saturn-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"74\" y=\"74\" width=\"12\" height=\"12\"/><path class=\"pg-a\" transform=\"rotate(90 81.44 80)\" d=\"M81.44 77.36L83.82 81.58L79.06 81.58Z\"/></g><path class=\"pg-dpo\" d=\"M62 62H74V74H86V86H74V98H62V86H50V74H62Z\"/><circle class=\"pg-dpc\" cx=\"68\" cy=\"80\" r=\"2.64\"/><g id=\"saturn-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"118\" y=\"100\" width=\"18\" height=\"8\" rx=\"4\"/></g><text class=\"pg-c\" x=\"127\" y=\"95\" font-size=\"4.6\">START</text><g id=\"saturn-x\" data-btn=\"x\"><circle class=\"pg-s\" cx=\"162\" cy=\"86\" r=\"7.5\"/><text class=\"pg-t\" x=\"162\" y=\"86.3\" font-size=\"7.88\">X</text></g><g id=\"saturn-y\" data-btn=\"y\"><circle class=\"pg-s\" cx=\"184\" cy=\"77\" r=\"7.5\"/><text class=\"pg-t\" x=\"184\" y=\"77.3\" font-size=\"7.88\">Y</text></g><g id=\"saturn-z\" data-btn=\"z\"><circle class=\"pg-s\" cx=\"206\" cy=\"72\" r=\"7.5\"/><text class=\"pg-t\" x=\"206\" y=\"72.3\" font-size=\"7.88\">Z</text></g><g id=\"saturn-a\" data-btn=\"a\"><circle class=\"pg-s\" cx=\"166\" cy=\"111\" r=\"9.5\"/><text class=\"pg-t\" x=\"166\" y=\"111.3\" font-size=\"9.97\">A</text></g><g id=\"saturn-b\" data-btn=\"b\"><circle class=\"pg-s\" cx=\"191\" cy=\"101\" r=\"9.5\"/><text class=\"pg-t\" x=\"191\" y=\"101.3\" font-size=\"9.97\">B</text></g><g id=\"saturn-c\" data-btn=\"c\"><circle class=\"pg-s\" cx=\"216\" cy=\"96\" r=\"9.5\"/><text class=\"pg-t\" x=\"216\" y=\"96.3\" font-size=\"9.97\">C</text></g></svg>",
  "sms": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"sms\" data-name=\"Master System\"><path class=\"pg-body\" d=\"M22 48H238Q244 48 244 54V126Q244 132 238 132H22Q16 132 16 126V54Q16 48 22 48Z\"/><g class=\"pg-d\"><rect x=\"24\" y=\"56\" width=\"80\" height=\"68\" rx=\"3\"/><path d=\"M110 48V62H244\"/><path d=\"M110 84H138M110 90H138M110 96H138M110 102H138M110 108H138\"/><rect x=\"144\" y=\"82\" width=\"44\" height=\"42\" rx=\"2\"/><rect x=\"194\" y=\"82\" width=\"44\" height=\"42\" rx=\"2\"/></g><text class=\"pg-c\" x=\"64\" y=\"63\" font-size=\"4.6\">CONTROL PAD</text><g class=\"pg-d\"><rect x=\"40\" y=\"70\" width=\"48\" height=\"48\" rx=\"6\"/></g><g id=\"sms-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"57.5\" y=\"74.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(0 64 79.44)\" d=\"M64 76.58L66.57 81.16L61.43 81.16Z\"/></g><g id=\"sms-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"57.5\" y=\"100.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(180 64 108.56)\" d=\"M64 105.7L66.57 110.28L61.43 110.28Z\"/></g><g id=\"sms-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"44.5\" y=\"87.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(270 49.44 94)\" d=\"M49.44 91.14L52.01 95.72L46.87 95.72Z\"/></g><g id=\"sms-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"70.5\" y=\"87.5\" width=\"13\" height=\"13\"/><path class=\"pg-a\" transform=\"rotate(90 78.56 94)\" d=\"M78.56 91.14L81.13 95.72L75.99 95.72Z\"/></g><path class=\"pg-dpo\" d=\"M57.5 74.5H70.5V87.5H83.5V100.5H70.5V113.5H57.5V100.5H44.5V87.5H57.5Z\"/><circle class=\"pg-dpc\" cx=\"64\" cy=\"94\" r=\"2.86\"/><text class=\"pg-c pg-cr\" x=\"166\" y=\"75\" font-size=\"5\">1 START</text><text class=\"pg-c pg-cr\" x=\"216\" y=\"75\" font-size=\"5\">2</text><g id=\"sms-b1\" data-btn=\"b1\"><circle class=\"pg-s\" cx=\"166\" cy=\"103\" r=\"13\"/><text class=\"pg-t\" x=\"166\" y=\"103.3\" font-size=\"7\">1</text></g><g id=\"sms-b2\" data-btn=\"b2\"><circle class=\"pg-s\" cx=\"216\" cy=\"103\" r=\"13\"/><text class=\"pg-t\" x=\"216\" y=\"103.3\" font-size=\"7\">2</text></g></svg>",
  "snes": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"snes\" data-name=\"Super Nintendo\"><g id=\"snes-l\" data-btn=\"l\"><path class=\"pg-s\" d=\"M15.43 55.89A61 61 0 0 1 47.15 31.99L48.7 36.74A56 56 0 0 0 19.57 58.69Z\"/></g><text class=\"pg-c\" x=\"42\" y=\"32\" font-size=\"5.5\">L</text><g id=\"snes-r\" data-btn=\"r\"><path class=\"pg-s\" d=\"M212.85 31.99A61 61 0 0 1 244.57 55.89L240.43 58.69A56 56 0 0 0 211.3 36.74Z\"/></g><text class=\"pg-c\" x=\"218\" y=\"32\" font-size=\"5.5\">R</text><path class=\"pg-body\" d=\"M66 34C90 34 104 42 130 42C156 42 170 34 194 34C228 34 252 58 252 90C252 122 228 146 194 146C170 146 156 138 130 138C104 138 90 146 66 146C32 146 8 122 8 90C8 58 32 34 66 34Z\"/><g class=\"pg-d\"><circle cx=\"66\" cy=\"90\" r=\"34\"/><ellipse cx=\"198\" cy=\"90\" rx=\"44\" ry=\"30\" transform=\"rotate(-34 198 90)\"/></g><g id=\"snes-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"59\" y=\"69\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(0 66 74.32)\" d=\"M66 71.24L68.77 76.17L63.23 76.17Z\"/></g><g id=\"snes-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"59\" y=\"97\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(180 66 105.68)\" d=\"M66 102.6L68.77 107.53L63.23 107.53Z\"/></g><g id=\"snes-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"45\" y=\"83\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(270 50.32 90)\" d=\"M50.32 86.92L53.09 91.85L47.55 91.85Z\"/></g><g id=\"snes-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"73\" y=\"83\" width=\"14\" height=\"14\"/><path class=\"pg-a\" transform=\"rotate(90 81.68 90)\" d=\"M81.68 86.92L84.45 91.85L78.91 91.85Z\"/></g><path class=\"pg-dpo\" d=\"M59 69H73V83H87V97H73V111H59V97H45V83H59Z\"/><circle class=\"pg-dpc\" cx=\"66\" cy=\"90\" r=\"3.08\"/><g id=\"snes-select\" data-btn=\"select\"><rect class=\"pg-s\" x=\"105\" y=\"94.5\" width=\"18\" height=\"7\" rx=\"3.5\" transform=\"rotate(-40 114 98)\"/></g><g id=\"snes-start\" data-btn=\"start\"><rect class=\"pg-s\" x=\"131\" y=\"94.5\" width=\"18\" height=\"7\" rx=\"3.5\" transform=\"rotate(-40 140 98)\"/></g><text class=\"pg-c\" x=\"112\" y=\"112\" font-size=\"4.4\">SELECT</text><text class=\"pg-c\" x=\"142\" y=\"112\" font-size=\"4.4\">START</text><g id=\"snes-x\" data-btn=\"x\" data-c=\"#3b5fd6\"><circle class=\"pg-s\" cx=\"198\" cy=\"66\" r=\"11\"/><text class=\"pg-t\" x=\"198\" y=\"66.3\" font-size=\"11.55\">X</text></g><g id=\"snes-a\" data-btn=\"a\" data-c=\"#d8333a\"><circle class=\"pg-s\" cx=\"222\" cy=\"90\" r=\"11\"/><text class=\"pg-t\" x=\"222\" y=\"90.3\" font-size=\"11.55\">A</text></g><g id=\"snes-b\" data-btn=\"b\" data-c=\"#e8c228\"><circle class=\"pg-s\" cx=\"198\" cy=\"114\" r=\"11\"/><text class=\"pg-t\" x=\"198\" y=\"114.3\" font-size=\"11.55\">B</text></g><g id=\"snes-y\" data-btn=\"y\" data-c=\"#2fa34a\"><circle class=\"pg-s\" cx=\"174\" cy=\"90\" r=\"11\"/><text class=\"pg-t\" x=\"174\" y=\"90.3\" font-size=\"11.55\">Y</text></g></svg>",
  "wii": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"wii\" data-name=\"Wii Classic Controller\"><g id=\"wii-l\" data-btn=\"l\"><rect class=\"pg-s\" x=\"23\" y=\"21.5\" width=\"34\" height=\"7\" rx=\"3.5\" transform=\"rotate(-10 40 25)\"/><text class=\"pg-t\" x=\"40\" y=\"25.3\" font-size=\"5.46\" transform=\"rotate(-10 40 25)\">L</text></g><g id=\"wii-r\" data-btn=\"r\"><rect class=\"pg-s\" x=\"203\" y=\"21.5\" width=\"34\" height=\"7\" rx=\"3.5\" transform=\"rotate(10 220 25)\"/><text class=\"pg-t\" x=\"220\" y=\"25.3\" font-size=\"5.46\" transform=\"rotate(10 220 25)\">R</text></g><g id=\"wii-zl\" data-btn=\"zl\"><rect class=\"pg-s\" x=\"88\" y=\"21\" width=\"20\" height=\"6\" rx=\"3\"/><text class=\"pg-t\" x=\"98\" y=\"24.3\" font-size=\"4.4\">ZL</text></g><g id=\"wii-zr\" data-btn=\"zr\"><rect class=\"pg-s\" x=\"152\" y=\"21\" width=\"20\" height=\"6\" rx=\"3\"/><text class=\"pg-t\" x=\"162\" y=\"24.3\" font-size=\"4.4\">ZR</text></g><path class=\"pg-body\" d=\"M130 28C166 27 196 25 216 26C246 28 254 56 252 86C250 122 236 146 210 146C190 146 178 138 162 138C150 138 142 138 130 138C118 138 110 138 98 138C82 138 70 146 50 146C24 146 10 122 8 86C6 56 14 28 44 26C64 25 94 27 130 28Z\"/><text class=\"pg-c\" x=\"130\" y=\"50\" font-size=\"8\">Wii</text><g id=\"wii-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"48.5\" y=\"47.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(0 54 51.68)\" d=\"M54 49.26L56.18 53.13L51.82 53.13Z\"/></g><g id=\"wii-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"48.5\" y=\"69.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(180 54 76.32)\" d=\"M54 73.9L56.18 77.77L51.82 77.77Z\"/></g><g id=\"wii-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"37.5\" y=\"58.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(270 41.68 64)\" d=\"M41.68 61.58L43.86 65.45L39.5 65.45Z\"/></g><g id=\"wii-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"59.5\" y=\"58.5\" width=\"11\" height=\"11\"/><path class=\"pg-a\" transform=\"rotate(90 66.32 64)\" d=\"M66.32 61.58L68.5 65.45L64.14 65.45Z\"/></g><path class=\"pg-dpo\" d=\"M48.5 47.5H59.5V58.5H70.5V69.5H59.5V80.5H48.5V69.5H37.5V58.5H48.5Z\"/><circle class=\"pg-dpc\" cx=\"54\" cy=\"64\" r=\"2.42\"/><g id=\"wii-minus\" data-btn=\"minus\"><circle class=\"pg-s\" cx=\"112\" cy=\"69\" r=\"5\"/><text class=\"pg-t\" x=\"112\" y=\"69.3\" font-size=\"7\">−</text></g><g id=\"wii-home\" data-btn=\"home\"><circle class=\"pg-s\" cx=\"130\" cy=\"69\" r=\"5\"/><text class=\"pg-t\" x=\"130\" y=\"69.3\" font-size=\"6\">⌂</text></g><g id=\"wii-plus\" data-btn=\"plus\"><circle class=\"pg-s\" cx=\"148\" cy=\"69\" r=\"5\"/><text class=\"pg-t\" x=\"148\" y=\"69.3\" font-size=\"7\">+</text></g><text class=\"pg-c\" x=\"112\" y=\"79\" font-size=\"4\">SELECT</text><text class=\"pg-c\" x=\"130\" y=\"79\" font-size=\"4\">HOME</text><text class=\"pg-c\" x=\"148\" y=\"79\" font-size=\"4\">START</text><g id=\"wii-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"7\"><path class=\"pg-gate\" d=\"M113.71 114.51L104.51 123.71L91.49 123.71L82.29 114.51L82.29 101.49L91.49 92.29L104.51 92.29L113.71 101.49Z\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"98\" cy=\"108\" r=\"10\"/><circle class=\"pg-kd\" cx=\"98\" cy=\"108\" r=\"5.5\"/></g></g><g id=\"wii-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"7\"><path class=\"pg-gate\" d=\"M177.71 114.51L168.51 123.71L155.49 123.71L146.29 114.51L146.29 101.49L155.49 92.29L168.51 92.29L177.71 101.49Z\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"108\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"108\" r=\"5.5\"/></g></g><g id=\"wii-x\" data-btn=\"x\"><circle class=\"pg-s\" cx=\"210\" cy=\"50\" r=\"8\"/><text class=\"pg-t\" x=\"210\" y=\"50.3\" font-size=\"8.4\">x</text></g><g id=\"wii-y\" data-btn=\"y\"><circle class=\"pg-s\" cx=\"190\" cy=\"68\" r=\"8\"/><text class=\"pg-t\" x=\"190\" y=\"68.3\" font-size=\"8.4\">y</text></g><g id=\"wii-a\" data-btn=\"a\"><circle class=\"pg-s\" cx=\"230\" cy=\"68\" r=\"8\"/><text class=\"pg-t\" x=\"230\" y=\"68.3\" font-size=\"8.4\">a</text></g><g id=\"wii-b\" data-btn=\"b\"><circle class=\"pg-s\" cx=\"210\" cy=\"86\" r=\"8\"/><text class=\"pg-t\" x=\"210\" y=\"86.3\" font-size=\"8.4\">b</text></g></svg>",
  "x360": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"x360\" data-name=\"Xbox 360\"><g id=\"x360-lt\" data-btn=\"lt\"><rect class=\"pg-s\" x=\"45\" y=\"7.5\" width=\"30\" height=\"9\" rx=\"4\"/><text class=\"pg-t\" x=\"60\" y=\"12.3\" font-size=\"7.02\">LT</text></g><g id=\"x360-rt\" data-btn=\"rt\"><rect class=\"pg-s\" x=\"185\" y=\"7.5\" width=\"30\" height=\"9\" rx=\"4\"/><text class=\"pg-t\" x=\"200\" y=\"12.3\" font-size=\"7.02\">RT</text></g><g id=\"x360-lb\" data-btn=\"lb\"><path class=\"pg-s\" d=\"M38 30C44 22 70 20 84 24L86 30C70 28 50 30 40 36Z\"/><text class=\"pg-t\" x=\"62\" y=\"27.5\" font-size=\"4.6\">LB</text></g><g id=\"x360-rb\" data-btn=\"rb\"><path class=\"pg-s\" d=\"M222 30C216 22 190 20 176 24L174 30C190 28 210 30 220 36Z\"/><text class=\"pg-t\" x=\"198\" y=\"27.5\" font-size=\"4.6\">RB</text></g><path class=\"pg-body\" d=\"M130 30C160 28 190 25 214 28C238 32 247 52 250 80C255 118 257 154 236 162C218 168 207 148 196 132C186 118 170 116 130 117C90 116 74 118 64 132C53 148 42 168 24 162C3 154 5 118 10 80C13 52 22 32 46 28C70 25 100 28 130 30Z\"/><g id=\"x360-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"62\" cy=\"62\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"62\" cy=\"62\" r=\"10\"/><circle class=\"pg-kd\" cx=\"62\" cy=\"62\" r=\"5.5\"/></g></g><g class=\"pg-d\"><circle cx=\"98\" cy=\"100\" r=\"17\"/></g><g id=\"x360-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"93.5\" y=\"86.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(0 98 89.92)\" d=\"M98 87.94L99.78 91.11L96.22 91.11Z\"/></g><g id=\"x360-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"93.5\" y=\"104.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(180 98 110.08)\" d=\"M98 108.1L99.78 111.27L96.22 111.27Z\"/></g><g id=\"x360-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"84.5\" y=\"95.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(270 87.92 100)\" d=\"M87.92 98.02L89.7 101.19L86.14 101.19Z\"/></g><g id=\"x360-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"102.5\" y=\"95.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(90 108.08 100)\" d=\"M108.08 98.02L109.86 101.19L106.3 101.19Z\"/></g><path class=\"pg-dpo\" d=\"M93.5 86.5H102.5V95.5H111.5V104.5H102.5V113.5H93.5V104.5H84.5V95.5H93.5Z\"/><circle class=\"pg-dpc\" cx=\"98\" cy=\"100\" r=\"1.98\"/><g id=\"x360-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"162\" cy=\"100\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"100\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"100\" r=\"5.5\"/></g></g><g id=\"x360-back\" data-btn=\"back\"><circle class=\"pg-s\" cx=\"110\" cy=\"62\" r=\"4.5\"/></g><g id=\"x360-guide\" data-btn=\"guide\"><circle class=\"pg-s\" cx=\"130\" cy=\"62\" r=\"9\"/><text class=\"pg-t\" x=\"130\" y=\"62.3\" font-size=\"7\">X</text></g><g id=\"x360-start\" data-btn=\"start\"><circle class=\"pg-s\" cx=\"150\" cy=\"62\" r=\"4.5\"/></g><text class=\"pg-c\" x=\"110\" y=\"71\" font-size=\"3.8\">BACK</text><text class=\"pg-c\" x=\"150\" y=\"71\" font-size=\"3.8\">START</text><g id=\"x360-y\" data-btn=\"y\" data-c=\"#e8b93a\"><circle class=\"pg-s\" cx=\"196\" cy=\"48\" r=\"7\"/><text class=\"pg-t\" x=\"196\" y=\"48.3\" font-size=\"7.35\">Y</text></g><g id=\"x360-b\" data-btn=\"b\" data-c=\"#e04b3a\"><circle class=\"pg-s\" cx=\"210\" cy=\"62\" r=\"7\"/><text class=\"pg-t\" x=\"210\" y=\"62.3\" font-size=\"7.35\">B</text></g><g id=\"x360-a\" data-btn=\"a\" data-c=\"#3fae49\"><circle class=\"pg-s\" cx=\"196\" cy=\"76\" r=\"7\"/><text class=\"pg-t\" x=\"196\" y=\"76.3\" font-size=\"7.35\">A</text></g><g id=\"x360-x\" data-btn=\"x\" data-c=\"#3a78d6\"><circle class=\"pg-s\" cx=\"182\" cy=\"62\" r=\"7\"/><text class=\"pg-t\" x=\"182\" y=\"62.3\" font-size=\"7.35\">X</text></g></svg>",
  "xbox": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"xbox\" data-name=\"Xbox (Controller S)\"><g id=\"xbox-lt\" data-btn=\"lt\"><rect class=\"pg-s\" x=\"35\" y=\"10\" width=\"34\" height=\"8\" rx=\"4\" transform=\"rotate(-12 52 14)\"/><text class=\"pg-t\" x=\"52\" y=\"14.3\" font-size=\"6.24\" transform=\"rotate(-12 52 14)\">L</text></g><g id=\"xbox-rt\" data-btn=\"rt\"><rect class=\"pg-s\" x=\"191\" y=\"10\" width=\"34\" height=\"8\" rx=\"4\" transform=\"rotate(12 208 14)\"/><text class=\"pg-t\" x=\"208\" y=\"14.3\" font-size=\"6.24\" transform=\"rotate(12 208 14)\">R</text></g><path class=\"pg-body\" d=\"M130 22C162 20 198 14 226 20C246 26 252 56 250 84C248 116 254 150 238 164C222 174 206 160 196 140C186 124 172 122 154 124C144 125 138 126 130 126C122 126 116 125 106 124C88 122 74 124 64 140C54 160 38 174 22 164C6 150 12 116 10 84C8 56 14 26 34 20C62 14 98 20 130 22Z\"/><g class=\"pg-d\"><circle cx=\"130\" cy=\"46\" r=\"15\"/><path d=\"M122 38L138 54M138 38L122 54\"/></g><g id=\"xbox-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"6\"><circle class=\"pg-gate\" cx=\"60\" cy=\"56\" r=\"17\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"60\" cy=\"56\" r=\"11\"/><circle class=\"pg-kd\" cx=\"60\" cy=\"56\" r=\"6.05\"/></g></g><g class=\"pg-d\"><circle cx=\"100\" cy=\"96\" r=\"19\"/></g><g id=\"xbox-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"95.5\" y=\"82.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(0 100 85.92)\" d=\"M100 83.94L101.78 87.11L98.22 87.11Z\"/></g><g id=\"xbox-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"95.5\" y=\"100.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(180 100 106.08)\" d=\"M100 104.1L101.78 107.27L98.22 107.27Z\"/></g><g id=\"xbox-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"86.5\" y=\"91.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(270 89.92 96)\" d=\"M89.92 94.02L91.7 97.19L88.14 97.19Z\"/></g><g id=\"xbox-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"104.5\" y=\"91.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(90 110.08 96)\" d=\"M110.08 94.02L111.86 97.19L108.3 97.19Z\"/></g><path class=\"pg-dpo\" d=\"M95.5 82.5H104.5V91.5H113.5V100.5H104.5V109.5H95.5V100.5H86.5V91.5H95.5Z\"/><circle class=\"pg-dpc\" cx=\"100\" cy=\"96\" r=\"1.98\"/><g id=\"xbox-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"6\"><circle class=\"pg-gate\" cx=\"164\" cy=\"96\" r=\"17\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"164\" cy=\"96\" r=\"11\"/><circle class=\"pg-kd\" cx=\"164\" cy=\"96\" r=\"6.05\"/></g></g><g id=\"xbox-back\" data-btn=\"back\"><circle class=\"pg-s\" cx=\"34\" cy=\"92\" r=\"5\"/></g><g id=\"xbox-start\" data-btn=\"start\"><circle class=\"pg-s\" cx=\"46\" cy=\"102\" r=\"5\"/></g><text class=\"pg-c\" x=\"30\" y=\"101\" font-size=\"3.8\">BACK</text><text class=\"pg-c\" x=\"46\" y=\"111\" font-size=\"3.8\">START</text><g id=\"xbox-y\" data-btn=\"y\" data-c=\"#e8b93a\"><circle class=\"pg-s\" cx=\"198\" cy=\"30\" r=\"7\"/><text class=\"pg-t\" x=\"198\" y=\"30.3\" font-size=\"7.35\">Y</text></g><g id=\"xbox-b\" data-btn=\"b\" data-c=\"#e04b3a\"><circle class=\"pg-s\" cx=\"213\" cy=\"42\" r=\"7\"/><text class=\"pg-t\" x=\"213\" y=\"42.3\" font-size=\"7.35\">B</text></g><g id=\"xbox-x\" data-btn=\"x\" data-c=\"#3a78d6\"><circle class=\"pg-s\" cx=\"183\" cy=\"42\" r=\"7\"/><text class=\"pg-t\" x=\"183\" y=\"42.3\" font-size=\"7.35\">X</text></g><g id=\"xbox-a\" data-btn=\"a\" data-c=\"#3fae49\"><circle class=\"pg-s\" cx=\"198\" cy=\"54\" r=\"7\"/><text class=\"pg-t\" x=\"198\" y=\"54.3\" font-size=\"7.35\">A</text></g><g id=\"xbox-black\" data-btn=\"black\"><circle class=\"pg-s\" cx=\"226\" cy=\"62\" r=\"6.5\"/><text class=\"pg-t\" x=\"226\" y=\"62.3\" font-size=\"4.2\">BK</text></g><g id=\"xbox-white\" data-btn=\"white\" data-c=\"#eeeeee\"><circle class=\"pg-s\" cx=\"214\" cy=\"76\" r=\"6.5\"/><text class=\"pg-t\" x=\"214\" y=\"76.3\" font-size=\"4.2\">WH</text></g></svg>",
  "xinput": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 260 170\" data-glyph=\"xinput\" data-name=\"Xbox controller\"><g id=\"xinput-lt\" data-btn=\"lt\"><rect class=\"pg-s\" x=\"45\" y=\"7.5\" width=\"30\" height=\"9\" rx=\"4\"/><text class=\"pg-t\" x=\"60\" y=\"12.3\" font-size=\"7.02\">LT</text></g><g id=\"xinput-rt\" data-btn=\"rt\"><rect class=\"pg-s\" x=\"185\" y=\"7.5\" width=\"30\" height=\"9\" rx=\"4\"/><text class=\"pg-t\" x=\"200\" y=\"12.3\" font-size=\"7.02\">RT</text></g><g id=\"xinput-lb\" data-btn=\"lb\"><path class=\"pg-s\" d=\"M38 30C44 22 70 20 84 24L86 30C70 28 50 30 40 36Z\"/><text class=\"pg-t\" x=\"62\" y=\"27.5\" font-size=\"4.6\">LB</text></g><g id=\"xinput-rb\" data-btn=\"rb\"><path class=\"pg-s\" d=\"M222 30C216 22 190 20 176 24L174 30C190 28 210 30 220 36Z\"/><text class=\"pg-t\" x=\"198\" y=\"27.5\" font-size=\"4.6\">RB</text></g><path class=\"pg-body\" d=\"M130 30C160 28 190 25 214 28C238 32 247 52 250 80C255 118 257 154 236 162C218 168 207 148 196 132C186 118 170 116 130 117C90 116 74 118 64 132C53 148 42 168 24 162C3 154 5 118 10 80C13 52 22 32 46 28C70 25 100 28 130 30Z\"/><g id=\"xinput-lstick\" data-btn=\"lstick\" data-stick=\"l\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"62\" cy=\"62\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"62\" cy=\"62\" r=\"10\"/><circle class=\"pg-kd\" cx=\"62\" cy=\"62\" r=\"5.5\"/></g></g><g class=\"pg-d\"><circle cx=\"98\" cy=\"100\" r=\"17\"/></g><g id=\"xinput-up\" data-btn=\"up\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"93.5\" y=\"86.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(0 98 89.92)\" d=\"M98 87.94L99.78 91.11L96.22 91.11Z\"/></g><g id=\"xinput-down\" data-btn=\"down\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"93.5\" y=\"104.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(180 98 110.08)\" d=\"M98 108.1L99.78 111.27L96.22 111.27Z\"/></g><g id=\"xinput-left\" data-btn=\"left\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"84.5\" y=\"95.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(270 87.92 100)\" d=\"M87.92 98.02L89.7 101.19L86.14 101.19Z\"/></g><g id=\"xinput-right\" data-btn=\"right\" class=\"pg-arm\"><rect class=\"pg-s\" x=\"102.5\" y=\"95.5\" width=\"9\" height=\"9\"/><path class=\"pg-a\" transform=\"rotate(90 108.08 100)\" d=\"M108.08 98.02L109.86 101.19L106.3 101.19Z\"/></g><path class=\"pg-dpo\" d=\"M93.5 86.5H102.5V95.5H111.5V104.5H102.5V113.5H93.5V104.5H84.5V95.5H93.5Z\"/><circle class=\"pg-dpc\" cx=\"98\" cy=\"100\" r=\"1.98\"/><g id=\"xinput-rstick\" data-btn=\"rstick\" data-stick=\"r\" data-travel=\"5\"><circle class=\"pg-gate\" cx=\"162\" cy=\"100\" r=\"15\"/><g class=\"pg-knob\"><circle class=\"pg-s\" cx=\"162\" cy=\"100\" r=\"10\"/><circle class=\"pg-kd\" cx=\"162\" cy=\"100\" r=\"5.5\"/></g></g><g id=\"xinput-guide\" data-btn=\"guide\"><circle class=\"pg-s\" cx=\"130\" cy=\"44\" r=\"7.5\"/><text class=\"pg-t\" x=\"130\" y=\"44.3\" font-size=\"6\">X</text></g><g id=\"xinput-view\" data-btn=\"view\"><circle class=\"pg-s\" cx=\"112\" cy=\"64\" r=\"4.5\"/></g><g id=\"xinput-menu\" data-btn=\"menu\"><circle class=\"pg-s\" cx=\"148\" cy=\"64\" r=\"4.5\"/></g><g id=\"xinput-share\" data-btn=\"share\"><rect class=\"pg-s\" x=\"126\" y=\"73.75\" width=\"8\" height=\"4.5\" rx=\"2.25\"/></g><text class=\"pg-c\" x=\"112\" y=\"73\" font-size=\"3.8\">VIEW</text><text class=\"pg-c\" x=\"148\" y=\"73\" font-size=\"3.8\">MENU</text><g id=\"xinput-y\" data-btn=\"y\" data-c=\"#e8b93a\"><circle class=\"pg-s\" cx=\"196\" cy=\"48\" r=\"7\"/><text class=\"pg-t\" x=\"196\" y=\"48.3\" font-size=\"7.35\">Y</text></g><g id=\"xinput-b\" data-btn=\"b\" data-c=\"#e04b3a\"><circle class=\"pg-s\" cx=\"210\" cy=\"62\" r=\"7\"/><text class=\"pg-t\" x=\"210\" y=\"62.3\" font-size=\"7.35\">B</text></g><g id=\"xinput-a\" data-btn=\"a\" data-c=\"#3fae49\"><circle class=\"pg-s\" cx=\"196\" cy=\"76\" r=\"7\"/><text class=\"pg-t\" x=\"196\" y=\"76.3\" font-size=\"7.35\">A</text></g><g id=\"xinput-x\" data-btn=\"x\" data-c=\"#3a78d6\"><circle class=\"pg-s\" cx=\"182\" cy=\"62\" r=\"7\"/><text class=\"pg-t\" x=\"182\" y=\"62.3\" font-size=\"7.35\">X</text></g></svg>",
};
/* GLYPHS-END */
// console button (data-btn in the SVG) -> RetroPad key(s), first = what a click presses; unlisted names map to themselves
const STICK_KEYS = { lstick: "l3 lup ldown lleft lright", rstick: "r3 rup rdown rleft rright" };
const PS_MAP = { m: { triangle: "x", circle: "a", cross: "b", square: "y", l1: "l", r1: "r", ps: "home" },
                 alt: { duckstation: { triangle: "y", circle: "b", cross: "a", square: "x" } } };
const XB_MAP = { a: "b", b: "a", x: "y", y: "x", lb: "l", rb: "r", lt: "l2", rt: "r2", back: "select", view: "select", menu: "start", guide: "home" };
const GLYPH_DEFS = {
  // N64 C buttons are the right analog stick (both cores; RetroPad X / A only reach C-up / C-right with R2 held, which
  // n64CMode shows as c_up / c_right): a click on one deflects the right stick that way
  n64: { m: { a: "b", b: "y", z: "l2", cup: "rup cup c_up", cright: "rright cright c_right", cdown: "rdown cdown c_down", cleft: "rleft cleft c_left" },
         remap: n64CMode },
  gc: { m: { z: "r", l: "l2", r: "r2", rstick: "r3 rup rdown rleft rright cup cdown cleft cright" },     // dolphin libretro
        alt: { dolphin: { l: "l l2", r: "r r2", z: "z select" } } },                                     // standalone Dolphin
  wii: { m: { l: "l2", r: "r2", zl: "l", zr: "r", minus: "select", plus: "start" } },                     // Dolphin: Classic Controller
  md3: { m: { a: "y", b: "b", c: "a" } },                                                                 // genesis_plus_gx
  md6: { m: { a: "y", b: "b", c: "a", x: "l", y: "x", z: "r", mode: "select" } },
  sms: { m: { b1: "b", b2: "a" } },
  saturn: { m: { a: "b", b: "a", c: "l", x: "y", y: "x", z: "r", l: "l2", r: "r2" } },                   // yabasanshiro / beetle
  dc: { m: { a: "b", b: "a", x: "y", y: "x", l: "l2", r: "r2" } },                                       // flycast
  ps1: PS_MAP, ds1: PS_MAP, ps2: PS_MAP, ps3: PS_MAP, psp: PS_MAP,
  xbox: { m: { ...XB_MAP, white: "l", black: "r" } }, x360: { m: XB_MAP }, xinput: { m: XB_MAP },
  arcade: { m: { b1: "b", b2: "a", b3: "y", b4: "x", b5: "l", b6: "r", b7: "l2", b8: "r2", coin: "select",
                 stick: "lup ldown lleft lright up down left right" },                                    // libretro MAME / FBNeo / Flycast NAOMI
            alt: { mame: { b1: "a", b2: "b", b3: "x", b4: "y" } } },                                     // standalone MAME
};
const GLYPH_OF = {
  n64: "n64", n64dd: "n64", snes: "snes", sfc: "snes", sgb: "snes", satellaview: "snes", superfamicom: "snes",
  nes: "nes", fds: "nes", famicom: "nes", gb: "gb", gameboy: "gb", gbc: "gbc", gba: "gba",
  gamecube: "gc", gc: "gc", ngc: "gc", wii: "wii", wiiclassic: "wii",
  genesis: "md6", megadrive: "md6", md: "md6", md6: "md6", segacd: "md6", megacd: "md6", sega32x: "md6", "32x": "md6",
  md3: "md3", genesis3: "md3", sms: "sms", mastersystem: "sms", mark3: "sms", sg1000: "sms", gamegear: "sms",
  saturn: "saturn", dreamcast: "dc", dc: "dc",
  naomi: "arcade", atomiswave: "arcade", arcade: "arcade", mame: "arcade", neogeo: "arcade", fbneo: "arcade",
  cps1: "arcade", cps2: "arcade", cps3: "arcade", segaarcadepc: "arcade",
  psx: "ds1", ps1: "ds1", playstation: "ds1", dualshock: "ds1", psxdigital: "ps1", ps1digital: "ps1",
  ps2: "ps2", ps3: "ps3", psp: "psp",
  xbox: "xbox", xbox360: "x360", x360: "x360", xinput: "xinput", xboxone: "xinput", xboxseries: "xinput", pc: "xinput", windows: "xinput",
};
const GLYPH_RX = [            // long system names ("Sega Dreamcast", "Sony PlayStation 2", ...)
  [/dreamcast/, "dc"], [/naomi|atomiswave|arcade|mame|fbneo|neogeo|cps\d/, "arcade"], [/saturn/, "saturn"],
  [/genesis|megadrive/, "md6"], [/mastersystem/, "sms"], [/gamecube/, "gc"], [/wii(?!u)/, "wii"],
  [/nintendo64|n64/, "n64"], [/superfamicom|supernintendo|snes/, "snes"], [/gameboyadvance/, "gba"],
  [/gameboycolou?r/, "gbc"], [/gameboy/, "gb"], [/playstationportable|psp/, "psp"], [/playstation3|ps3/, "ps3"],
  [/playstation2|ps2/, "ps2"], [/playstation|psx/, "ds1"], [/xbox360/, "x360"], [/xbox/, "xbox"],
  [/nintendoentertainment|famicom|nes$/, "nes"],
];
const normPlat = p => String(p || "").toLowerCase().replace(/[^a-z0-9]/g, "");
function glyphOf(p) {
  const k = normPlat(p);
  if (!k) return null;
  const g = GLYPH_OF[k] || (GLYPH_RX.find(([rx]) => rx.test(k)) || [])[1];
  return g && SVG[g] ? g : null;
}
const kindOf = p => { const g = glyphOf(p); return g ? "svg:" + g : famOf(p); };
function wireSVG(svg, def, variant) {         // data-btn parts -> the .pg-b / data-k / knob markup the drawing code expects
  const alt = (def.alt && def.alt[variant]) || {}, m = def.m || {};
  for (const g of svg.querySelectorAll("[data-btn]")) {
    const b = g.dataset.btn, c = g.dataset.c;
    g.dataset.k = alt[b] || m[b] || STICK_KEYS[b] || b;
    g.classList.add("pg-b", c ? "col" : "nt");
    g.style.setProperty("--c", c || GREY);
    if (g.dataset.stick) {
      g.classList.add("pg-stk");
      const k = g.querySelector(".pg-knob");
      if (k) { k.dataset.stick = g.dataset.stick; k.dataset.m = g.dataset.travel || "0"; k.dataset.dirs = g.dataset.dirs || "0"; }
    }
  }
}

// ---------- styles ----------
const CSS = `
.pg{--pg-gbox:#a78bfa;--pg-lit:color-mix(in srgb,currentColor 86%,transparent);color:var(--fg,#e8e8ee);display:block;max-width:280px;font-family:system-ui,sans-serif;line-height:1}
.pg svg{display:block;width:100%;height:auto;overflow:visible}
.pg .pg-body{fill:color-mix(in srgb,currentColor 5%,transparent);stroke:color-mix(in srgb,currentColor 42%,transparent);stroke-width:1.3;stroke-linejoin:round}
.pg .pg-d *{fill:none;stroke:color-mix(in srgb,currentColor 20%,transparent);stroke-width:1}
.pg .pg-s{fill:color-mix(in srgb,currentColor 4%,transparent);stroke:color-mix(in srgb,currentColor 58%,transparent);stroke-width:1.2;transition:fill 50ms,stroke 50ms}
.pg .pg-t{fill:color-mix(in srgb,currentColor 72%,transparent);font-weight:600;text-anchor:middle;dominant-baseline:central;pointer-events:none}
.pg .pg-c{fill:color-mix(in srgb,currentColor 45%,transparent);font-weight:600;text-anchor:middle;dominant-baseline:central;letter-spacing:.3px}
.pg .pg-y{fill:none;stroke:color-mix(in srgb,currentColor 72%,transparent);stroke-width:1.3;stroke-linejoin:round;stroke-linecap:round}
.pg .pg-a{fill:color-mix(in srgb,currentColor 60%,transparent)}
.pg .pg-arm .pg-s{fill:transparent;stroke:none}
.pg .pg-arm .pg-a{fill:color-mix(in srgb,currentColor 38%,transparent)}
.pg .pg-dpo{fill:none;stroke:color-mix(in srgb,currentColor 58%,transparent);stroke-width:1.2;stroke-linejoin:round}
.pg .pg-dpb{fill:none;stroke:color-mix(in srgb,currentColor 24%,transparent);stroke-width:1}
.pg .pg-dpc{fill:none;stroke:color-mix(in srgb,currentColor 22%,transparent);stroke-width:1}
.pg .pg-gate{fill:color-mix(in srgb,currentColor 3%,transparent);stroke:color-mix(in srgb,currentColor 32%,transparent);stroke-width:1;stroke-dasharray:2 2}
.pg .pg-kd{fill:none;stroke:color-mix(in srgb,currentColor 30%,transparent);stroke-width:1}
.pg .pg-knob{transition:transform 60ms linear}
.pg .on .pg-s{fill:var(--c);stroke:currentColor;stroke-width:1.4}
.pg .on.g .pg-s{stroke:var(--pg-gbox);stroke-width:2}
.pg .on.g{filter:drop-shadow(0 0 2.5px var(--pg-gbox))}
.pg .on .pg-t{fill:#111114}.pg .on .pg-y{stroke:#111114}.pg .on .pg-a{fill:#111114}.pg .on .pg-kd{stroke:#11111466}
.pg .on.nt .pg-t{fill:var(--bg,#16161a)}.pg .on.nt .pg-a{fill:var(--bg,#16161a)}.pg .on.nt .pg-kd{stroke:var(--bg,#16161a)}
.pg .pg-stk.mv .pg-gate{stroke:color-mix(in srgb,currentColor 55%,transparent)}
.pg .pg-stk.mv.g .pg-gate{stroke:var(--pg-gbox)}
.pg .pg-cr{fill:color-mix(in srgb,#e0453a 85%,transparent)}
.pg .col:not(.on) .pg-s{fill:color-mix(in srgb,var(--c) 15%,transparent);stroke:color-mix(in srgb,var(--c) 85%,transparent)}
.pg .col:not(.on) .pg-t{fill:var(--c)}.pg .col:not(.on) .pg-y{stroke:var(--c)}.pg .col:not(.on) .pg-a{fill:var(--c)}
.pg .pg-stk.col:not(.on) .pg-gate{stroke:color-mix(in srgb,var(--c) 45%,transparent)}
.pg-cap{display:flex;justify-content:space-between;gap:8px;margin-top:2px;font-size:11px;color:var(--mut,#9a9aa6)}
.pg-src{font-weight:600}.pg-src.p{color:var(--fg,#e8e8ee)}.pg-src.g{color:var(--pg-gbox)}
`;
function injectCSS() {
  if (document.getElementById("padglyph-css")) return;
  const s = document.createElement("style"); s.id = "padglyph-css"; s.textContent = CSS; document.head.appendChild(s);
}

// ---------- local pad (reuses index.html's pads()/cfgFor()/pressed() when they exist) ----------
const XBOX = { 0: "b", 1: "a", 2: "y", 3: "x", 4: "l", 5: "r", 6: "l2", 7: "r2", 8: "select", 9: "start", 10: "l3", 11: "r3", 12: "up", 13: "down", 14: "left", 15: "right" };
function ownPressed(gp, c) {
  const out = new Set();
  gp.buttons.forEach((b, i) => { if ((b.pressed || b.value > .5) && c.map[i]) out.add(c.map[i]); });
  return out;
}
function nativePressed() {
  const live = window.GBOX_NATIVE_PAD_STATE;
  if (!live || Date.now() - live.at > 1000) return null;
  const pad = live.pads?.find(p => p.slot === 0) || live.pads?.[0];
  if (!pad) return null;
  const held = new Set();
  for (const [bit, key] of [[0x1000, "b"], [0x2000, "a"], [0x4000, "y"], [0x8000, "x"],
    [0x0100, "l"], [0x0200, "r"], [0x0020, "select"], [0x0010, "start"],
    [0x0040, "l3"], [0x0080, "r3"], [0x0001, "up"], [0x0002, "down"],
    [0x0004, "left"], [0x0008, "right"]]) if (pad.buttons & bit) held.add(key);
  if (pad.lt > 127) held.add("l2");
  if (pad.rt > 127) held.add("r2");
  const axis = v => Math.abs(v / 32767) > DZ ? Math.max(-1, Math.min(1, v / 32767)) : 0;
  const stick = { x: axis(pad.lx), y: -axis(pad.ly) };
  const rstick = { x: axis(pad.rx), y: -axis(pad.ry) };
  stickDirs(held, stick, rstick);                       // N64: the right stick lights the C buttons
  return { held, stick, rstick };
}
function stickDirs(held, st, rs) {
  for (const [p, v] of [["l", st], ["r", rs]]) {
    if (v.y < -.5) held.add(p + "up"); if (v.y > .5) held.add(p + "down");
    if (v.x < -.5) held.add(p + "left"); if (v.x > .5) held.add(p + "right");
  }
}
function readLocal() {
  // index.html's reading first: Player 1's pad (the desktop's XInput state while it is fresh) through the console's
  // controller map, i.e. what the game receives (clients/web/viz/pad-map.js)
  if (typeof API.local === "function") { try { const r = API.local(); return r ? { ...r, held: new Set(r.held || []) } : null; } catch { return null; } }
  const native = nativePressed();
  if (native) return native;
  let list;
  try { list = typeof pads === "function" ? pads() : [...(navigator.getGamepads ? navigator.getGamepads() : [])].filter(Boolean); } catch { return null; }
  for (const gp of list) {
    let c = null;
    try { c = typeof cfgFor === "function" ? cfgFor(gp) : null; } catch {}
    c = c || { player: gp.index === 0 ? 1 : 0, map: XBOX, stick: true };
    if (c.player !== 1) continue;
    let held;
    try { held = typeof pressed === "function" ? pressed(gp, c) : ownPressed(gp, c); } catch { held = ownPressed(gp, c); }
    held = new Set(held);
    const ax = i => Math.abs(gp.axes[i] || 0) > DZ ? gp.axes[i] : 0;
    const st = { x: ax(0), y: ax(1) }, rs = { x: ax(2), y: ax(3) };
    stickDirs(held, st, rs);
    return { held, stick: st, rstick: rs };
  }
  return null;
}
const token = o => o.token != null ? o.token : (typeof tok !== "undefined" ? tok : "");

// ---------- instances ----------
const insts = new Set();
let raf = 0;
function loop() {
  raf = 0;
  if (!insts.size) return;
  const loc = readLocal();
  for (const g of [...insts]) {
    if (!g.el.isConnected) { g.destroy(); continue; }
    g.local = loc; g.draw();
  }
  if (insts.size) raf = requestAnimationFrame(loop);
}
const kick = () => { if (!raf && insts.size) raf = requestAnimationFrame(loop); };
const LABEL = { player: "you", agent: "gBox · agent", autoplay: "gBox · autoplay", ui: "gBox · buttons" };

class Glyph {
  constructor(el, platform, opts) {
    this.el = el; this.opts = opts; this.sid = opts.sid || null;
    this.plat = platform || opts.platform || ""; this.fixed = !!platform; this.adapter = opts.adapter || "";
    this.manual = null; this.remote = null; this.local = null; this.sig = ""; this.visible = true; this.alive = true;
    injectCSS(); this.build();
    if ("IntersectionObserver" in window) {
      this.io = new IntersectionObserver(es => { this.visible = es[es.length - 1].isIntersecting; }); this.io.observe(el);
    }
    if (this.sid) this.poll();
    insts.add(this); kick();
  }
  build() {
    const v = VARIANT[String(this.adapter).toLowerCase()] || "", gk = glyphOf(this.plat);
    this.fam = kindOf(this.plat); this.glyph = gk; this.sig = "";
    this.el.classList.add("pg");
    const capHTML = name => `<div class="pg-cap"><span class="pg-name">${name}</span><span class="pg-src"></span></div>`;
    if (gk) {
      const def = GLYPH_DEFS[gk] || {}, name = (SVG[gk].match(/data-name="([^"]*)"/) || [])[1] || gk;
      this.layout = { name, remap: def.remap };
      this.el.innerHTML = SVG[gk] + capHTML(name);
      const svg = this.el.querySelector("svg");
      svg.setAttribute("role", "img"); svg.setAttribute("aria-label", name + " controller");
      wireSVG(svg, def, v);
    } else {
      const L = LAYOUTS[famOf(this.plat)]();
      this.layout = L;
      this.el.innerHTML = `<svg viewBox="0 0 ${VB_W} ${VB_H}" role="img" aria-label="${L.name} controller">${L.body}${L.parts.map(p => partSVG(p, v)).join("")}</svg>` +
        capHTML(L.name);
    }
    this.btns = [...this.el.querySelectorAll(".pg-b")].map(g => ({ g, keys: g.dataset.k.split(" ").filter(Boolean) }));
    this.knobs = [...this.el.querySelectorAll(".pg-knob")].map(k => ({ k, id: k.dataset.stick, m: +k.dataset.m, dirs: k.dataset.dirs === "1", grp: k.parentNode }));
    this.srcEl = this.el.querySelector(".pg-src");
  }
  setPlatform(platform, adapter) {
    this.plat = platform || this.plat; this.fixed = !!platform; if (adapter != null) this.adapter = adapter; this.build(); kick();
  }
  update(state) { this.manual = state ? { ...state, held: new Set(state.held || []) } : null; kick(); }
  poll() {
    const go = async () => {
      if (!this.alive) return;
      if (this.el.isConnected && (!this.remote || (!document.hidden && this.visible))) {   // first poll always: it names the platform
        try {
          const r = await fetch(`${this.opts.base || ""}/api/sessions/${encodeURIComponent(this.sid)}/pad`,
            { headers: { authorization: "Bearer " + token(this.opts) }, cache: "no-store" });
          if (r.ok) this.onRemote(await r.json());
        } catch {}
      }
      if (this.alive) this.timer = setTimeout(go, 100);
    };
    go();
  }
  onRemote(j) {
    this.remote = j;
    const plat = this.fixed ? this.plat : (j.platform || this.plat), ad = j.adapter || this.adapter;
    if (kindOf(plat) !== this.fam || (VARIANT[ad] || "") !== (VARIANT[this.adapter] || "")) { this.plat = plat; this.adapter = ad; this.build(); }
    kick();
  }
  heldMap() {
    const held = new Map(), r = this.remote, loc = this.local, man = this.manual;
    if (r && r.held) for (const k of r.held) {
      const s = (r.sources && r.sources[k]) || r.source || "agent";
      if (s === "player" && loc && loc.held && (loc.held.size || loc.held.length)) continue;   // shown live from the Gamepad API
      held.set(k, s);
    }
    if (man) for (const k of man.held) held.set(k, man.source || "player");
    if (loc) for (const k of loc.held) held.set(k, "player");
    if (held.has("z") && VARIANT[this.adapter] !== "dolphin" && !held.has("b")) held.set("b", held.get("z"));   // keyboard z = B
    return this.layout.remap ? this.layout.remap(held) : held;
  }
  stickVec(id, held, dirs) {
    const an = [this.local, this.manual, this.remote].map(s => s && (id === "l" ? s.stick : s.rstick)).find(v => v && (v.x || v.y));
    if (an) return [an.x, an.y];
    const p = id === "l" ? ["l"] : ["r", "c"], has = d => p.some(q => held.has(q + d)) || (dirs && held.has(d));
    let x = (has("right") ? 1 : 0) - (has("left") ? 1 : 0), y = (has("down") ? 1 : 0) - (has("up") ? 1 : 0);
    if (x && y) { x *= .7071; y *= .7071; }
    return [x, y];
  }
  stickSrc(id) {                                       // who is deflecting this stick analog-wise (local pad / manual)
    const pick = s => s && (id === "l" ? s.stick : s.rstick), moved = v => v && (v.x || v.y);
    if (moved(pick(this.local))) return "player";
    if (moved(pick(this.manual))) return this.manual.source || "player";
    if (moved(pick(this.remote))) return "player";
    return null;
  }
  draw() {
    const held = this.heldMap();
    const vecs = this.knobs.map(kn => this.stickVec(kn.id, held, kn.dirs));
    const sig = [...held].map(e => e.join(":")).sort().join(",") + "|" + vecs.map(v => v.map(x => x.toFixed(2)).join(",")).join(";");
    if (sig === this.sig) return;
    this.sig = sig;
    for (const { g, keys } of this.btns) {
      let src = null;
      for (const k of keys) if (held.has(k)) { src = held.get(k); break; }
      if (g.classList.contains("pg-stk")) continue;      // sticks: handled below (lit on click, ring on deflection)
      g.classList.toggle("on", !!src); g.classList.toggle("g", !!src && src !== "player");
    }
    this.knobs.forEach((kn, i) => {
      const [x, y] = vecs[i], m = Math.min(1, Math.hypot(x, y)) / (Math.hypot(x, y) || 1);
      kn.k.style.transform = `translate(${(x * m * kn.m).toFixed(2)}px,${(y * m * kn.m).toFixed(2)}px)`;
      const click = kn.id === "l" ? "l3" : "r3", keys = kn.grp.dataset.k.split(" ");
      const dirSrc = keys.map(k => held.get(k)).find(Boolean) || this.stickSrc(kn.id);
      const moved = !!(x || y);
      kn.grp.classList.toggle("mv", moved);
      kn.grp.classList.toggle("on", held.has(click) || (moved && !!dirSrc));
      const src = held.get(click) || dirSrc;
      kn.grp.classList.toggle("g", !!src && src !== "player");
    });
    const srcs = new Set(held.values());
    const gb = [...srcs].find(s => s !== "player");
    this.srcEl.textContent = (gb && srcs.has("player") ? "you + " : "") + (gb ? LABEL[gb] || "gBox" : srcs.has("player") ? "you" : "");
    this.srcEl.className = "pg-src " + (gb ? "g" : srcs.size ? "p" : "");
  }
  destroy() {
    this.alive = false; clearTimeout(this.timer); this.io && this.io.disconnect(); insts.delete(this);
  }
}

const API = {
  mount(el, platform, opts = {}) {
    if (typeof el === "string") el = document.querySelector(el);
    if (!el) return null;
    for (const g of insts) if (g.el === el) g.destroy();
    return new Glyph(el, platform, opts);
  },
  update(state) { for (const g of insts) g.update(state); },
  unmount(el) { for (const g of insts) if (!el || g.el === el) { g.destroy(); if (g.el.isConnected) g.el.innerHTML = ""; } },
  family: famOf,
  families: Object.keys(LAYOUTS),
  glyph: glyphOf,                 // platform -> SVG glyph key, or null (built-in drawing)
  glyphs: Object.keys(SVG),
  local: null,          // optional override: () => ({held, stick, rstick}) | null
};
window.PadGlyph = API;
})();
