// Extract tab: the scene you're playing, frozen as 3D. Area geometry (gBox asset package) + live entities from the
// game's RAM (class, pointer, position, heading), with an outliner, selection, move gizmo, inspector and exports.
import * as T from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { OBJExporter } from "three/addons/exporters/OBJExporter.js";

const X = { r: null, scene: null, cam: null, orbit: null, gizmo: null, area: null, ents: new T.Group(), sel: null, items: [], sid: null, state: null };
const KIND_COLOR = { player: 0x4cc26b, npc: 0x7c96ff, enemy: 0xff6b6b, object: 0xe0a400, gate: 0x00d0d0 };
// ponytail: area guess from what's alive in RAM (Pioneer 2 has TObjNpc* townspeople); add a RAM area id when profiled
const guessArea = st => (st.entities || []).some(e => /^TObjNpc/.test(e.class || "")) ? "pso_dc_city00" : "pso_dc_forest01";
const q = s => document.querySelector(s);
const tok = () => encodeURIComponent(S.tok || "");

function ui() {
  const sec = q("#extract");
  sec.innerHTML = `<div id="xt">
    <div class="xbar"><b id="xt-title">Extract</b><select id="xt-area" title="Area geometry"></select>
      <button class="act" id="xt-snap" title="Re-read the live game (entities, positions) and rebuild the scene">⟳ Snapshot</button>
      <button class="act" id="xt-extract" title="Extract another PSO area from the disc into an asset package">⬇ Extract area…</button>
      <span class="sp"></span><button class="act" id="xt-blender" title="Selected object -> gBox clipboard (Blender: gBox > Paste)">📋 Copy to Blender</button>
      <button class="act" id="xt-glb">⬇ GLB</button><button class="act" id="xt-obj">⬇ OBJ</button>
      <button class="act" id="xt-fbx" title="Whole area as FBX (Blender converts it)">⬇ FBX</button><button class="act" id="xt-abc">⬇ ABC</button>
      <span id="xt-msg" class="mut"></span></div>
    <div class="xmain"><div id="xt-out"></div><div id="xt-view"><canvas></canvas><div class="xhint">drag: orbit · right-drag: pan · wheel: zoom · click: select · W/E: move/rotate · H: hide · F: focus</div></div>
      <div id="xt-ins" class="mut">Select something in the scene or the outliner.</div></div></div>`;
  const cv = q("#xt-view canvas");
  X.r = new T.WebGLRenderer({ canvas: cv, antialias: true }); X.r.outputColorSpace = T.SRGBColorSpace; X.r.setPixelRatio(Math.min(devicePixelRatio, 2));
  X.scene = new T.Scene(); X.scene.background = new T.Color(0x0b0d14); X.scene.fog = new T.Fog(0x0b0d14, 400, 4000);
  X.scene.add(new T.HemisphereLight(0xffffff, 0x223344, 2.4)); const d = new T.DirectionalLight(0xffffff, 1.6); d.position.set(200, 500, 300); X.scene.add(d);
  X.cam = new T.PerspectiveCamera(55, 1, 0.5, 20000);
  X.orbit = new OrbitControls(X.cam, cv); X.orbit.enableDamping = true;
  X.gizmo = new TransformControls(X.cam, cv); X.gizmo.addEventListener("dragging-changed", e => X.orbit.enabled = !e.value); X.scene.add(X.gizmo);
  X.scene.add(X.ents);
  const ray = new T.Raycaster(); let down = null;
  cv.addEventListener("pointerdown", e => down = [e.clientX, e.clientY]);
  cv.addEventListener("pointerup", e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || X.gizmo.dragging) return;
    const b = cv.getBoundingClientRect(); ray.setFromCamera({ x: (e.clientX - b.left) / b.width * 2 - 1, y: -(e.clientY - b.top) / b.height * 2 + 1 }, X.cam);
    const hit = ray.intersectObjects(X.items.map(i => i.obj).filter(o => o.visible), true)[0];
    select(hit ? X.items.find(i => i.obj === hit.object || i.obj.getObjectById(hit.object.id)) : null);
  });
  addEventListener("keydown", e => {
    if (!sec.classList.contains("on") || e.target.closest("input, textarea, select")) return;
    if (e.key === "w") X.gizmo.setMode("translate"); if (e.key === "e") X.gizmo.setMode("rotate");
    if (e.key === "h" && X.sel) { X.sel.obj.visible = !X.sel.obj.visible; outliner(); }
    if (e.key === "f" && X.sel) focus(X.sel.obj);
  });
  q("#xt-snap").onclick = snapshot; q("#xt-area").onchange = () => loadArea(q("#xt-area").value);
  q("#xt-blender").onclick = toBlender; q("#xt-glb").onclick = () => download("glb"); q("#xt-obj").onclick = () => download("obj");
  q("#xt-fbx").onclick = () => areaExport("fbx"); q("#xt-abc").onclick = () => areaExport("abc");
  q("#xt-extract").onclick = extractArea;
  q("#xt-out").onclick = e => { const r = e.target.closest("[data-i]"); if (!r) return; const it = X.items[+r.dataset.i];
    if (e.target.closest(".eye")) { it.obj.visible = !it.obj.visible; if (!it.obj.visible && X.sel === it) select(null); outliner(); } else { select(it); focus(it.obj); } };
  const frame = () => { if (sec.classList.contains("on")) { const w = cv.clientWidth, h = cv.clientHeight;
      if (w && cv.width !== Math.round(w * X.r.getPixelRatio())) { X.r.setSize(w, h, false); X.cam.aspect = w / h; X.cam.updateProjectionMatrix(); }
      X.orbit.update(); X.r.render(X.scene, X.cam); } requestAnimationFrame(frame); };
  frame();
}
const msg = t => q("#xt-msg").textContent = t;

async function api(p, body) { const r = await gbox.api(p, body); if (!r.ok) throw new Error(r.error); return r.data; }

async function snapshot() {
  try {
    const ctx = await chatContext().catch(() => ({}));
    X.sid = ctx.session_id || EMB.sid;
    const pk = await api("/api/uap");
    q("#xt-area").innerHTML = pk.map(p => `<option value="${esc(p.package)}">${esc(p.package)} · ${p.triangles || "?"} tris</option>`).join("");
    if (!X.sid) { q("#xt-title").textContent = "Extract · no game running"; msg("Start a game to snapshot its scene; you can still browse extracted areas."); if (pk[0]) loadArea(pk[0].package); return; }
    q("#xt-title").textContent = "Extract · " + (ctx.game_title || "live game");
    msg("reading the live scene from RAM…");
    let st = {};
    try { st = await api(`/api/sessions/${X.sid}/rpc`, { op: "state", args: {} }); } catch (e) { msg("no scene profile for this game yet: " + e.message); }
    X.state = st;
    const area = (st.entities ? guessArea(st) : null);
    if (area && pk.some(p => p.package === area)) q("#xt-area").value = area;
    await loadArea(q("#xt-area").value);
    entities(st);
    msg(`${(st.entities || []).length} entities · snapshot ${new Date().toLocaleTimeString()}`);
  } catch (e) { msg("⚠ " + e.message); }
}

async function loadArea(pkg) {
  if (!pkg) return;
  msg("loading " + pkg + "…");
  if (X.area) { X.scene.remove(X.area); X.area.traverse(o => { o.geometry?.dispose(); }); }
  if (!S.tok) S.tok = await gbox.token();
  const res = await fetch(`${S.apiUrl}/api/uap/${encodeURIComponent(pkg)}/export?fmt=glb&token=${tok()}`);
  if (!res.ok) throw new Error(`${pkg}: ${res.status} ${(await res.text()).slice(0, 160)}`);
  const buf = await res.arrayBuffer();
  const g = await new GLTFLoader().parseAsync(buf, "");
  X.area = g.scene; X.area.name = pkg; X.scene.add(X.area);
  X.items = X.items.filter(i => i.kind === "entity");
  X.area.traverse(o => { if (o.isMesh) X.items.push({ kind: "mesh", obj: o, name: o.name || o.parent?.name || "mesh" }); });
  outliner();
  if (!X.state?.entities?.length) focus(X.area);
  msg(`${pkg}: ${X.items.filter(i => i.kind === "mesh").length} meshes`);
}

function entities(st) {
  X.ents.clear(); X.items = X.items.filter(i => i.kind !== "entity");
  for (const e of st.entities || []) {
    const grp = new T.Group(); grp.name = `${e.class} #${e.slot}`;
    const body = new T.Mesh(new T.CapsuleGeometry(4, 10, 4, 12), new T.MeshStandardMaterial({ color: KIND_COLOR[e.kind] || 0xaaaaaa, emissive: KIND_COLOR[e.kind] || 0, emissiveIntensity: 0.35 }));
    body.position.y = 9; grp.add(body);
    const nose = new T.Mesh(new T.ConeGeometry(2.4, 6, 10), body.material); nose.rotation.x = Math.PI / 2; nose.position.set(0, 14, 5); grp.add(nose);
    grp.position.set(e.x, e.y, e.z); grp.rotation.y = (e.heading_deg ?? 0) * Math.PI / 180;
    const c = document.createElement("canvas"); c.width = 256; c.height = 48; const x = c.getContext("2d");
    x.fillStyle = "#000a"; x.fillRect(0, 0, 256, 48); x.fillStyle = "#fff"; x.font = "22px system-ui"; x.textAlign = "center"; x.fillText(e.class.replace(/^TObj/, ""), 128, 32);
    const lab = new T.Sprite(new T.SpriteMaterial({ map: new T.CanvasTexture(c), depthTest: false })); lab.scale.set(28, 5.2, 1); lab.position.y = 26; grp.add(lab);
    X.ents.add(grp); X.items.push({ kind: "entity", obj: grp, name: grp.name, e });
  }
  outliner();
  const p = (st.entities || []).find(e => e.kind === "player");
  if (p) {                                                        // start where you're standing, looking the way you face
    const h = (p.heading_deg ?? 0) * Math.PI / 180, back = new T.Vector3(-Math.sin(h), 0, -Math.cos(h)).multiplyScalar(60);
    X.cam.position.set(p.x + back.x, p.y + 35, p.z + back.z); X.orbit.target.set(p.x, p.y + 10, p.z); X.orbit.update();
  }
}

function outliner() {
  const row = (it, i) => `<div class="xr ${X.sel === it ? "on" : ""} ${it.obj.visible ? "" : "off"}" data-i="${i}">
      <span class="eye" title="show/hide">${it.obj.visible ? "👁" : "🙈"}</span><span class="nm">${esc(it.name)}</span></div>`;
  const ents = X.items.map((it, i) => it.kind === "entity" ? row(it, i) : "").join(""), meshes = X.items.map((it, i) => it.kind === "mesh" ? row(it, i) : "").join("");
  q("#xt-out").innerHTML = `<details open><summary>Entities (live RAM)</summary>${ents || '<p class="mut">none</p>'}</details>
    <details ${meshes.length < 40000 ? "open" : ""}><summary>Area · ${esc(X.area?.name || "")}</summary>${meshes}</details>`;
}

const box = new T.BoxHelper(undefined, 0xffd400);
async function select(it) {
  X.sel = it; X.gizmo.detach(); X.scene.remove(box);
  if (!it) { q("#xt-ins").innerHTML = "Select something in the scene or the outliner."; outliner(); return; }
  box.setFromObject(it.obj); X.scene.add(box); X.gizmo.attach(it.obj); outliner();
  const ins = q("#xt-ins");
  if (it.kind === "mesh") {
    const g = it.obj.geometry, m = it.obj.material, img = m.map?.image;
    let thumb = "";
    if (img) { const c = document.createElement("canvas"); c.width = 128; c.height = 128 * (img.height / img.width || 1); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); thumb = `<img class="xtex" title="Click to inspect the texture" src="${c.toDataURL()}">`; X.texImg = img; }
    ins.innerHTML = `<h4>${esc(it.name)}</h4><table class="kv"><tr><td>type</td><td>area mesh</td></tr><tr><td>vertices</td><td>${g.attributes.position.count}</td></tr>
      <tr><td>triangles</td><td>${(g.index ? g.index.count : g.attributes.position.count) / 3}</td></tr><tr><td>material</td><td>${esc(m.name || "")}</td></tr>
      <tr><td>package</td><td>${esc(X.area.name)}</td></tr></table>${thumb}<p class="mut">Textures and geometry come from the disc (d.rel + PVM).</p>`;
    ins.querySelector(".xtex")?.addEventListener("click", () => texView(X.texImg, m.name || it.name));
    return;
  }
  const e = it.e;
  ins.innerHTML = `<h4>${esc(e.class)} <span class="mut">#${e.slot}</span></h4><table class="kv">${Object.entries(e).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`).join("")}</table>
    <div class="mut">RAM at ${esc(e.ptr || "?")}</div><pre id="xt-hex">reading…</pre><button class="act" id="xt-ask">💬 Ask gBox about this</button>`;
  q("#xt-ask").onclick = () => { $("#chatpanel").classList.add("on"); chatSend(`In the Extract tab I selected entity ${e.class} (slot ${e.slot}, object at 0x${e.ptr}, room ${e.room}, position ${e.x},${e.y},${e.z}). What is it, what does its structure hold, and what can I change about it?`); };
  try {
    const hex = await api(`/api/sessions/${X.sid}/rpc`, { op: "read_memory", args: { address: parseInt(e.ptr, 16), length: 192 } });
    const h = typeof hex === "string" ? hex : hex.hex || "";
    q("#xt-hex").textContent = h.match(/.{1,32}/g).map((l, i) => `+${(i * 16).toString(16).padStart(3, "0")}  ${l.match(/../g).join(" ")}`).join("\n");
  } catch (err) { q("#xt-hex").textContent = err.message; }
}

// ---------------- texture inspector: zoom / pan, channels, histogram ----------------
function texView(img, name) {
  let p = document.querySelector("#texv");
  if (!p) {
    document.body.insertAdjacentHTML("beforeend", `<div id="texv"><div class="ah"><b id="tv-name"></b><span class="mut" id="tv-info"></span>
      <span class="tvch">${["RGB", "R", "G", "B", "A", "Luma"].map(c => `<button data-c="${c}">${c}</button>`).join("")}</span>
      <label class="mut"><input type="checkbox" id="tv-px" checked> pixels</label><button class="act" id="tv-fit">Fit</button>
      <button class="act" id="tv-close">✕</button></div>
      <div class="tvbody"><canvas id="tv-cv"></canvas><canvas id="tv-hist" width="512" height="120"></canvas><div id="tv-px-info" class="mut"></div></div></div>`);
    p = document.querySelector("#texv");
    if (window.floating) floating(p, p.querySelector(".ah"), "texv");
    p.querySelector("#tv-close").onclick = () => p.classList.remove("on");
    p.querySelector(".tvch").onclick = e => { const c = e.target.dataset?.c; if (c) { TV.ch = c; tvDraw(); } };
    p.querySelector("#tv-px").onchange = tvDraw;
    p.querySelector("#tv-fit").onclick = () => { tvFit(); tvDraw(); };
    const cv = p.querySelector("#tv-cv");
    cv.addEventListener("wheel", e => { e.preventDefault(); const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const k = e.deltaY < 0 ? 1.25 : 0.8; TV.x = mx - (mx - TV.x) * k; TV.y = my - (my - TV.y) * k; TV.z *= k; tvDraw(); }, { passive: false });
    cv.addEventListener("pointerdown", e => { const sx = e.clientX - TV.x, sy = e.clientY - TV.y; cv.setPointerCapture(e.pointerId);
      cv.onpointermove = ev => { TV.x = ev.clientX - sx; TV.y = ev.clientY - sy; tvDraw(); }; cv.onpointerup = () => cv.onpointermove = null; });
    cv.addEventListener("mousemove", e => { const r = cv.getBoundingClientRect(), u = Math.floor((e.clientX - r.left - TV.x) / TV.z), v = Math.floor((e.clientY - r.top - TV.y) / TV.z);
      if (u < 0 || v < 0 || u >= TV.w || v >= TV.h) return; const i = (v * TV.w + u) * 4, d = TV.data;
      p.querySelector("#tv-px-info").textContent = `x ${u} y ${v} · R ${d[i]} G ${d[i + 1]} B ${d[i + 2]} A ${d[i + 3]} · #${[d[i], d[i + 1], d[i + 2]].map(x => x.toString(16).padStart(2, "0")).join("")}`; });
    new ResizeObserver(tvDraw).observe(cv);
  }
  const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; c.getContext("2d").drawImage(img, 0, 0);
  Object.assign(TV, { w: img.width, h: img.height, data: c.getContext("2d").getImageData(0, 0, img.width, img.height).data, ch: "RGB" });
  p.querySelector("#tv-name").textContent = name; p.querySelector("#tv-info").textContent = `${img.width}×${img.height}`;
  p.classList.add("on"); requestAnimationFrame(() => { tvFit(); tvDraw(); });
}
const TV = { z: 1, x: 0, y: 0, ch: "RGB" };
function tvFit() { const cv = document.querySelector("#tv-cv"); TV.z = Math.min(cv.clientWidth / TV.w, cv.clientHeight / TV.h) * 0.95;
  TV.x = (cv.clientWidth - TV.w * TV.z) / 2; TV.y = (cv.clientHeight - TV.h * TV.z) / 2; }
function tvDraw() {
  const cv = document.querySelector("#tv-cv"); if (!cv || !TV.data) return;
  cv.width = cv.clientWidth; cv.height = cv.clientHeight;
  const g = cv.getContext("2d"), src = new ImageData(TV.w, TV.h), d = TV.data, o = src.data, ch = TV.ch;
  for (let i = 0; i < d.length; i += 4) {
    const L = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    const v = ch === "R" ? d[i] : ch === "G" ? d[i + 1] : ch === "B" ? d[i + 2] : ch === "A" ? d[i + 3] : L;
    if (ch === "RGB") { o[i] = d[i]; o[i + 1] = d[i + 1]; o[i + 2] = d[i + 2]; o[i + 3] = d[i + 3]; }
    else { o[i] = o[i + 1] = o[i + 2] = v; o[i + 3] = 255; }
  }
  const t = document.createElement("canvas"); t.width = TV.w; t.height = TV.h; t.getContext("2d").putImageData(src, 0, 0);
  for (let y = 0; y < cv.height; y += 16) for (let x = 0; x < cv.width; x += 16) { g.fillStyle = (x + y) / 16 % 2 ? "#2a2a30" : "#1e1e24"; g.fillRect(x, y, 16, 16); }
  g.imageSmoothingEnabled = !document.querySelector("#tv-px").checked;
  g.drawImage(t, TV.x, TV.y, TV.w * TV.z, TV.h * TV.z);
  document.querySelectorAll("#texv .tvch button").forEach(b => b.classList.toggle("on", b.dataset.c === ch));
  // histogram of the channel(s) shown
  const hc = document.querySelector("#tv-hist"), hg = hc.getContext("2d"); hg.clearRect(0, 0, 512, 120); hg.fillStyle = "#111"; hg.fillRect(0, 0, 512, 120);
  const sets = ch === "RGB" ? [[0, "#ff5a5a"], [1, "#5aff7a"], [2, "#5a8cff"]] : [[{ R: 0, G: 1, B: 2, A: 3, Luma: -1 }[ch], "#ddd"]];
  hg.globalCompositeOperation = "lighter";
  for (const [k, col] of sets) {
    const h = new Uint32Array(256);
    for (let i = 0; i < d.length; i += 4) h[k < 0 ? Math.round(0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) : d[i + k]]++;
    const max = Math.max(...h) || 1; hg.fillStyle = col;
    for (let b = 0; b < 256; b++) { const v = Math.sqrt(h[b] / max) * 116; hg.fillRect(b * 2, 120 - v, 2, v); }
  }
  hg.globalCompositeOperation = "source-over";
}

function focus(o) {
  const b = new T.Box3().setFromObject(o), c = b.getCenter(new T.Vector3()), s = b.getSize(new T.Vector3()).length() || 50;
  X.orbit.target.copy(c); X.cam.position.copy(c).add(new T.Vector3(s * 0.6, s * 0.45, s * 0.6)); X.orbit.update();
}

function selectionRoot() {
  if (!X.sel) throw new Error("select something first");
  const o = X.sel.obj.clone(); o.position.set(0, 0, 0); return o;
}
async function toBlender() {
  try {
    const glb = await new GLTFExporter().parseAsync(selectionRoot(), { binary: true });
    const b64 = btoa(Array.from(new Uint8Array(glb), c => String.fromCharCode(c)).join(""));
    await api("/api/clipboard", { kind: "gltf", name: X.sel.name, b64, meta: { from: "extract", area: X.area?.name, binary: true } });
    msg("📋 On the gBox clipboard: in Blender press gBox ▸ Paste from gBox");
  } catch (e) { msg("⚠ " + e.message); }
}
async function download(fmt) {
  try {
    const root = selectionRoot(), data = fmt === "glb" ? await new GLTFExporter().parseAsync(root, { binary: true }) : new OBJExporter().parse(root);
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([data])), download: `${X.sel.name.replace(/[^\w-]+/g, "_")}.${fmt}` });
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) { msg("⚠ " + e.message); }
}
function areaExport(fmt) {
  if (!X.area) return msg("load an area first");
  msg(`⏳ ${fmt.toUpperCase()} export of ${X.area.name} (Blender converts it on a PC that has Blender)…`);
  gbox.openExternal(`${S.apiUrl}/api/uap/${encodeURIComponent(X.area.name)}/export?fmt=${fmt}&token=${tok()}`);
}
async function extractArea() {
  const area = prompt("PSO area to extract (e.g. FOREST01, FOREST02, CAVE01, MACHINE01, ANCIENT01, CITY00):", "FOREST02"); if (!area) return;
  msg(`⏳ extracting ${area} on the Spark…`);
  try {
    let j = await api("/api/jobs", { tool: "extract_pso_area", input: { disc: "/home/ehm_eckx/gbox-cache/dc/psov2.gdi", area }, require_os: "linux" });
    while (["queued", "running"].includes(j.state)) { await new Promise(z => setTimeout(z, 1500)); j = await api(`/api/jobs/${j.id}`); }
    if (j.state !== "succeeded") throw new Error(j.error || j.state);
    await snapshot(); q("#xt-area").value = `pso_dc_${area.toLowerCase()}`; loadArea(q("#xt-area").value);
  } catch (e) { msg("⚠ " + e.message); }
}

ui();
// every visit is a fresh snapshot of the moment you left the game (area + where everyone is right now)
document.querySelector('aside button[data-s="extract"]').addEventListener("click", () => snapshot());
