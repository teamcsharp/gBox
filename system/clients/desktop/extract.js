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
    let full = "";
    if (img) {                                              // thumbnail in the inspector; the full texture opens in the texture pop-up (#186)
      const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; c.getContext("2d").drawImage(img, 0, 0); full = c.toDataURL();
      const t = document.createElement("canvas"); t.width = 128; t.height = Math.max(1, Math.round(128 * (img.height / img.width || 1))); t.getContext("2d").drawImage(img, 0, 0, t.width, t.height);
      thumb = `<img class="xtex tpable" title="Click to inspect the texture: zoom, channels, histogram, save" data-name="${esc(m.name || it.name)}" src="${t.toDataURL()}">`;
    }
    ins.innerHTML = `<h4>${esc(it.name)}</h4><table class="kv"><tr><td>type</td><td>area mesh</td></tr><tr><td>vertices</td><td>${g.attributes.position.count}</td></tr>
      <tr><td>triangles</td><td>${(g.index ? g.index.count : g.attributes.position.count) / 3}</td></tr><tr><td>material</td><td>${esc(m.name || "")}</td></tr>
      <tr><td>package</td><td>${esc(X.area.name)}</td></tr></table>${thumb}<p class="mut">Textures and geometry come from the disc (d.rel + PVM).</p>`;
    const tex = ins.querySelector(".xtex"); if (tex) tex.tpSrc = full;   // the pop-up reads the full-size pixels from here
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
