// Detailed report (#1011): a three.js bubble graph of how a request was worked. The task sits at the centre; every recorded
// subtask (the ticket's task steps, the resolution agent's tool calls, the Hermes run's steps and the automated
// sub-requests) orbits it in order; the gBox tools they used sit on the outer ring, each tied to the subtasks that called
// it. Click a bubble to focus it (the camera glides there and the card shows its tool, input and result); the request's
// screenshots slide in and out on the right; "Evidence & attempts" opens the flat report on top. Pure parts (model,
// layout, cardHtml) take plain data so they are testable without WebGL.
window.GBoxReportGraph = (function () {
  const COLORS = { task: 0x7c96ff, done: 0x2ecc71, failed: 0xff4d4d, running: 0xffb020, step: 0xb07cff, sub: 0xff7ad9, tool: 0x00d0d0 };
  const KIND = { task: "Task", step: "Subtask", sub: "Automated sub-request", tool: "Tool" };
  const RG = { on: false, three: null, graph: null, pos: null, meshes: [], lines: [], sel: null, request: null, images: [], image: null, shot: false, deps: null, raf: 0, built: false };
  const short = (v, n = 600) => {
    if (v == null || v === "") return "";
    const s = typeof v === "string" ? v : JSON.stringify(v, null, 1);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  };
  // a recorded status word -> done | failed | running | step (unknown)
  function statusOf(s) {
    const t = String(s || "").toLowerCase();
    if (!t) return "step";
    if (/fail|error|reject|cancel|blocked|incomplete|disputed/.test(t)) return "failed";
    if (/run|progress|pending|await|start|queued|open|thinking|preparing/.test(t)) return "running";
    if (/done|ok|succe|finish|complete|verified|ready|saved|applied|merged/.test(t)) return "done";
    return "step";
  }
  // The graph's data, pure. nodes: {id, kind: task|step|sub|tool, label, status, color, tool, input, result, text, attempt, ts, images, count, uses, n}
  // edges: {from, to, kind: order (task -> first subtask -> next ...) | branch (task -> sub-request) | data (subtask -> tool)}
  function model(request, extra = {}) {
    const x = request || {}, nodes = [], edges = [], tools = new Map(), steps = [];
    const shots = m => (m?.attachments || []).filter(a => (a.type || "").startsWith("image/") && a.sha256).map(a => a.sha256);
    const task = { id: "task", kind: "task", label: `#${x.number ?? "?"} ${x.title || "Request"}`.trim(), status: statusOf(x.status === "done" ? "done" : x.status),
                   rawStatus: x.status || "", text: x.body || "", images: x.image ? [x.image] : [], tool: null, input: null, result: "", n: -1 };
    nodes.push(task);
    const useTool = (name, from, count = 1, use = null) => {
      if (!name) return;
      const id = "tool:" + name;
      let t = tools.get(id);
      if (!t) { t = { id, kind: "tool", label: name, status: "step", count: 0, uses: [], tool: name, input: null, result: "", images: [] }; tools.set(id, t); }
      t.count += count; if (use) t.uses.push(use);
      if (!edges.some(e => e.from === from && e.to === id)) edges.push({ from, to: id, kind: "data" });
    };
    const addStep = s => { s.n = steps.length; steps.push(s); nodes.push(s); if (s.tool) useTool(s.tool, s.id, 1, { step: s.id, label: s.label, status: s.status }); };
    (x.messages || []).forEach((m, i) => {
      const ts = m.task_step; if (!ts || !(m.author === "agent" || m.author === "system")) return;
      addStep({ id: "msg:" + i, kind: "step", label: ts.action || `Update ${i + 1}`, status: statusOf(ts.status), rawStatus: ts.status || "", attempt: ts.attempt || "",
                ts: m.ts, text: m.text || "", result: ts.result || "", input: null, tool: null, images: shots(m) });
    });
    for (const [src, run] of [["resolution", extra.resolution], ["run", extra.run]]) {
      (run?.steps || []).forEach((s, i) => {
        const name = s.action || s.tool || "step", isTool = s.input !== undefined || src === "resolution";
        addStep({ id: `${src}:${i}`, kind: "step", label: name + (Number(s.attempt) > 1 ? ` · try ${s.attempt}` : ""), status: statusOf(s.status), rawStatus: s.status || "",
                  attempt: s.attempt || "", ts: s.ts, text: src === "run" ? `Hermes run ${run.name || run.id || ""}`.trim() : "Resolution agent", result: s.result || "",
                  input: s.input === undefined ? null : s.input, tool: isTool ? name : null, images: [] });
      });
    }
    steps.forEach((s, i) => edges.push(i === 0 ? { from: "task", to: s.id, kind: "order" } : { from: steps[i - 1].id, to: s.id, kind: "order" }));
    (extra.children || []).forEach((c, k) => {
      const id = "req:" + c.id;
      nodes.push({ id, kind: "sub", label: `#${c.number ?? "?"} ${c.title || ""}`.trim(), status: statusOf(c.status === "done" ? "done" : c.status), rawStatus: c.status || "",
                   text: c.body || "", result: (c.messages || []).filter(m => m.author === "agent").map(m => m.text).slice(-1)[0] || "", input: null, tool: null,
                   images: c.image ? [c.image] : [], n: steps.length + k, requestId: c.id });
      edges.push({ from: "task", to: id, kind: "branch" });
      for (const [name, count] of Object.entries(c.metrics?.tools || {})) useTool(name, id, Number(count) || 1);
    });
    for (const [name, count] of Object.entries(x.metrics?.tools || {})) if (!tools.has("tool:" + name)) useTool(name, "task", Number(count) || 1);
    nodes.push(...tools.values());
    for (const n of nodes) n.color = n.kind === "tool" ? COLORS.tool : n.kind === "task" ? COLORS.task
                                   : n.kind === "sub" ? (n.status === "failed" ? COLORS.failed : COLORS.sub) : (COLORS[n.status] || COLORS.step);
    return { nodes, edges, title: task.label, status: x.status || "" };
  }
  // Positions, pure: the task at the centre, the subtasks on a ring in order (a gentle descending spiral), the tools on the
  // outer ring in the order of the subtasks that use them. Returns {id: {x, y, z, r (bubble radius), a (angle)}}.
  function layout(graph) {
    const pos = {}, ring = graph.nodes.filter(n => n.kind === "step" || n.kind === "sub").sort((a, b) => (a.n ?? 0) - (b.n ?? 0));
    const tools = graph.nodes.filter(n => n.kind === "tool");
    const n = Math.max(1, ring.length), R1 = 5.5 + 0.35 * Math.max(0, n - 6), R2 = R1 + 4.5;
    pos.task = { x: 0, y: 0, z: 0, r: 1.25, a: 0 };
    ring.forEach((s, i) => {
      const a = -Math.PI / 2 + i * 2 * Math.PI / n, uses = graph.edges.filter(e => e.from === s.id && e.kind === "data").length;
      pos[s.id] = { x: Math.cos(a) * R1, y: 1.2 - (n > 1 ? i / (n - 1) : 0.5) * 2.4, z: Math.sin(a) * R1, r: (s.kind === "sub" ? 0.72 : 0.55) + 0.05 * Math.min(6, uses), a };
    });
    const mean = t => {                                           // circular mean of the angles of the bubbles this tool serves
      const from = graph.edges.filter(e => e.to === t.id).map(e => pos[e.from]).filter(Boolean);
      if (!from.length) return 0;
      return Math.atan2(from.reduce((v, p) => v + Math.sin(p.a), 0), from.reduce((v, p) => v + Math.cos(p.a), 0));
    };
    const order = tools.map(t => ({ t, a: mean(t) })).sort((a, b) => a.a - b.a);
    const gap = 2 * Math.PI / Math.max(1, order.length), start = order.length ? order[0].a : 0;
    order.forEach(({ t, a }, i) => {                              // one slot each, in the order of their subtasks (a single tool sits by its subtask)
      const ang = order.length > 1 ? start + i * gap : a;
      pos[t.id] = { x: Math.cos(ang) * R2, y: -2 + 0.5 * Math.sin(i * 2.1), z: Math.sin(ang) * R2, r: Math.min(0.95, 0.42 + 0.1 * Math.log2(1 + (t.count || 1))), a: ang };
    });
    return pos;
  }
  // the focus card's HTML for a node (pure; esc escapes HTML)
  function cardHtml(n, esc) {
    if (!n) return "";
    const h = [`<h4><span class="rg-kind">${esc(KIND[n.kind] || n.kind)}</span>${esc(n.label)}</h4>`];
    const meta = [n.rawStatus && `status ${n.rawStatus.replace("_", " ")}`, n.attempt && `try ${n.attempt}`, n.ts && new Date(n.ts * 1000).toLocaleTimeString(),
                  n.kind === "tool" && `used ${n.count} time${n.count === 1 ? "" : "s"}`].filter(Boolean);
    if (meta.length) h.push(`<p class="mut">${esc(meta.join(" · "))}</p>`);
    if (n.tool && n.kind !== "tool") h.push(`<p><b>Tool</b> ${esc(n.tool)}</p>`);
    if (n.text) h.push(`<p>${esc(short(n.text, 400))}</p>`);
    if (n.input != null && n.input !== "") h.push(`<b>Input</b><pre>${esc(short(n.input))}</pre>`);
    if (n.result) h.push(`<b>Result</b><pre>${esc(short(n.result))}</pre>`);
    if (n.kind === "tool" && n.uses?.length) h.push(`<p class="mut">Called by ${n.uses.map(u => u.label).join(", ")}</p>`);
    h.push(`<div class="btns">${n.images?.length ? `<button class="act" data-rg-shot="${esc(n.images[0])}">Show its screenshot</button>` : ""}` +
           `${n.requestId ? `<button class="act" data-rg-open="${esc(n.requestId)}">Open this sub-request</button>` : ""}<button class="act" data-rg-back>Back to the whole task</button></div>`);
    return h.join("");
  }
  const CSS = [
    "#reportgraph { display:none; position:fixed; inset:80px 0 28px 0; z-index:1150; background:#07080cf5; color:var(--fg); flex-direction:column; }",
    "#reportgraph.on { display:flex; }",
    "#reportgraph .rg-head { display:flex; align-items:center; gap:10px; padding:8px 14px; border-bottom:1px solid var(--line); background:#0b0c10; }",
    "#reportgraph .rg-head b { flex:1; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }",
    "#reportgraph .rg-body { position:relative; flex:1; min-height:0; overflow:hidden; }",
    "#rg-canvas { width:100%; height:100%; display:block; cursor:grab; }",
    "#rg-legend { position:absolute; left:14px; bottom:10px; font-size:11px; pointer-events:none; display:flex; gap:12px; flex-wrap:wrap; }",
    "#rg-legend span::before { content:''; display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; background:var(--c); }",
    "#rg-card { position:absolute; left:14px; top:12px; width:min(380px,44vw); max-height:calc(100% - 60px); overflow:auto; background:#121420ee; border:1px solid var(--line);" +
      " border-radius:10px; padding:10px 12px; font-size:12.5px; box-shadow:0 12px 40px #000a; }",
    "#rg-card[hidden] { display:none; }",
    "#rg-card h4 { margin:0 0 6px; font-size:14px; overflow-wrap:anywhere; } #rg-card .rg-kind { display:block; font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--acc); }",
    "#rg-card p { margin:4px 0; overflow-wrap:anywhere; }",
    "#rg-card pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:180px; overflow:auto; background:#0a0b10; border-radius:6px; padding:6px 8px; font:11px/1.4 ui-monospace,Consolas,monospace; margin:4px 0 8px; }",
    "#rg-card .btns { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }",
    "#rg-shot { position:absolute; top:0; right:0; bottom:0; width:min(46%,760px); display:flex; flex-direction:column; background:#0b0c12f2; border-left:1px solid var(--line);" +
      " transform:translateX(100%); transition:transform .32s cubic-bezier(.2,.8,.2,1); box-shadow:-10px 0 30px #0008; }",
    "#rg-shot.on { transform:none; }",
    "#rg-shot .rg-shot-stage { flex:1; min-height:0; display:grid; place-items:center; padding:10px; }",
    "#rg-shot img { max-width:100%; max-height:100%; object-fit:contain; border:1px solid var(--line); border-radius:6px; background:#000; }",
    "#rg-shot img[hidden], #rg-shot-empty[hidden] { display:none; }",
    "#rg-shot-thumbs { display:flex; gap:8px; overflow:auto; padding:8px; border-top:1px solid var(--line); }",
    "#rg-shot-thumbs:empty { display:none; }",
    "#rg-shot-thumbs button { flex:none; border:2px solid transparent; background:var(--card); padding:2px; cursor:pointer; border-radius:4px; }",
    "#rg-shot-thumbs button[aria-pressed=true] { border-color:var(--acc); }",
    "#rg-shot-thumbs img { width:104px; height:66px; object-fit:contain; display:block; }",
    "#rg-shot-thumbs small { display:block; max-width:104px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10px; color:var(--mut); }",
  ].join("\n");
  const HTML = `<div id="reportgraph" role="dialog" aria-modal="true" aria-label="Detailed report">
  <div class="rg-head"><b id="rg-title">Detailed report</b><span id="rg-status" class="mut"></span>
    <button class="act" id="rg-shot-tog" aria-pressed="false" title="Slide the screenshot in or out">◂ Screenshot</button>
    <button class="act" id="rg-evidence" title="The flat report: screenshots, tasks, attempts and results">Evidence &amp; attempts</button>
    <button class="act" id="rg-close">Close</button></div>
  <div class="rg-body"><canvas id="rg-canvas" aria-label="Task graph: the request, its subtasks and the tools they used"></canvas>
    <div id="rg-legend" class="mut"><span style="--c:#7c96ff">Task</span><span style="--c:#2ecc71">Subtask done</span><span style="--c:#ffb020">Subtask running</span>
      <span style="--c:#ff4d4d">Subtask failed</span><span style="--c:#ff7ad9">Sub-request</span><span style="--c:#00d0d0">Tool</span><span style="--c:#556070">Click a bubble to focus · drag to orbit · wheel to zoom</span></div>
    <div id="rg-card" hidden></div>
    <aside id="rg-shot" aria-label="Request screenshot"><div class="rg-shot-stage"><img id="rg-shot-img" alt="Request screenshot" hidden><div id="rg-shot-empty" class="mut">No screenshot attached to this request.</div></div>
      <div id="rg-shot-thumbs"></div></aside></div></div>`;

  // the screenshot panel: in or out (pure DOM; deps.$ finds elements)
  function slide(on) {
    const $ = RG.deps.$, panel = $("#rg-shot"), tog = $("#rg-shot-tog");
    RG.shot = on === undefined ? !RG.shot : !!on;
    panel.classList.toggle("on", RG.shot);
    tog.setAttribute("aria-pressed", String(RG.shot)); tog.textContent = RG.shot ? "Screenshot ▸" : "◂ Screenshot";
    return RG.shot;
  }
  function showImage(sha) {
    const $ = RG.deps.$, item = RG.images.find(i => i.sha === sha) || RG.images[0] || null;
    RG.image = item ? item.sha : null;
    $("#rg-shot-img").hidden = !item; $("#rg-shot-empty").hidden = !!item;
    if (item) { $("#rg-shot-img").src = item.url; $("#rg-shot-img").alt = item.label; }
    for (const b of $("#rg-shot-thumbs").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.rgSha === RG.image));
  }
  function shots(x, tok, children = []) {
    const { $, esc, apiUrl } = RG.deps, list = [];
    if (x.image) list.push({ sha: x.image, label: "Original report screenshot" });
    for (const m of x.messages || []) for (const a of m.attachments || [])
      if ((a.type || "").startsWith("image/") && a.sha256) list.push({ sha: a.sha256, label: a.name || m.text || "Task screenshot" });
    for (const c of children) if (c.image && !list.some(z => z.sha === c.image)) list.push({ sha: c.image, label: `#${c.number ?? "?"} ${c.title || "sub-request"}` });
    RG.images = list.map(z => ({ ...z, url: `${apiUrl()}/api/artifacts/${z.sha}?token=${encodeURIComponent(tok)}` }));
    $("#rg-shot-thumbs").innerHTML = RG.images.map(z => `<button type="button" data-rg-sha="${esc(z.sha)}" aria-label="Show ${esc(z.label)}" aria-pressed="false"><img src="${esc(z.url)}" alt=""><small>${esc(z.label.slice(0, 30))}</small></button>`).join("");
    showImage(RG.images[0]?.sha);
    slide(RG.images.length > 0);
  }
  function card(n) {
    const $ = RG.deps.$, el = $("#rg-card");
    el.innerHTML = cardHtml(n, RG.deps.esc); el.hidden = !n;
  }
  // focus a bubble: the camera glides to it, its neighbours stay lit, the rest dims; null = the whole task
  function focus(id) {
    const m = RG.meshes.find(k => k.node.id === id) || null, T = RG.three;
    RG.sel = m ? m.node : null;
    if (T) {
      if (m) { T.goal.copy(m.home); T.goalDist = 6 + m.home.length() * 0.25; } else { T.goal.set(0, 0, 0); T.goalDist = 20; }
      const linked = new Set(m ? RG.graph.edges.filter(e => e.from === id || e.to === id).flatMap(e => [e.from, e.to]) : []);
      for (const k of RG.meshes) {
        const self = !m || k.node.id === id, near = linked.has(k.node.id);
        k.mat.emissiveIntensity = self ? (m ? 0.9 : 0.35) : near ? 0.5 : 0.1;
        k.mat.opacity = self || near ? 0.95 : 0.3; k.halo.material.opacity = self && m ? 0.22 : 0.1;
        k.label.material.opacity = self || near ? 1 : 0.25;
      }
    }
    card(RG.sel);
    if (RG.sel?.images?.length) { showImage(RG.sel.images[0]); slide(true); }
    return RG.sel;
  }
  function sprite(THREE, text, color, scale = 1) {
    const c = document.createElement("canvas"); c.width = 512; c.height = 96;
    const g = c.getContext("2d"); g.font = "600 30px Segoe UI, sans-serif"; g.textAlign = "center";
    g.fillStyle = "#" + color.toString(16).padStart(6, "0"); g.shadowColor = "#000"; g.shadowBlur = 6;
    g.fillText(text.length > 30 ? text.slice(0, 29) + "…" : text, 256, 58);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    s.scale.set(5.6 * scale, 1.05 * scale, 1); return s;
  }
  function build(THREE) {
    const T = RG.three, group = T.group;
    while (group.children.length) group.remove(group.children[0]);
    RG.meshes = []; RG.lines = [];
    const pos = RG.pos = layout(RG.graph);
    for (const n of RG.graph.nodes) {
      const p = pos[n.id]; if (!p) continue;
      const mat = new THREE.MeshStandardMaterial({ color: n.color, emissive: n.color, emissiveIntensity: 0.35, transparent: true, opacity: 0.92, roughness: 0.35, metalness: 0.1 });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(p.r, 32, 20), mat); mesh.position.set(p.x, p.y, p.z);
      const halo = new THREE.Mesh(new THREE.SphereGeometry(p.r * 1.45, 24, 16), new THREE.MeshBasicMaterial({ color: n.color, transparent: true, opacity: 0.1, depthWrite: false, side: THREE.BackSide }));
      mesh.add(halo);
      const label = sprite(THREE, n.kind === "task" ? n.label : n.label + (n.count > 1 ? ` ×${n.count}` : ""), n.color, n.kind === "task" ? 1.35 : 1);
      label.position.set(p.x, p.y + p.r + 0.55, p.z);
      group.add(mesh, label);
      RG.meshes.push({ node: n, mesh, mat, halo, label, home: new THREE.Vector3(p.x, p.y, p.z), pulse: n.status === "running" });
    }
    for (const e of RG.graph.edges) {
      const a = pos[e.from], b = pos[e.to]; if (!a || !b) continue;
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a.x, a.y, a.z), new THREE.Vector3(b.x, b.y, b.z)]);
      const line = new THREE.Line(geo, e.kind === "data" ? new THREE.LineDashedMaterial({ color: 0x3f8f99, dashSize: 0.35, gapSize: 0.25, transparent: true, opacity: 0.7 })
                                                     : new THREE.LineBasicMaterial({ color: e.kind === "branch" ? 0x9a5f9a : 0x6a7590, transparent: true, opacity: 0.9 }));
      if (e.kind === "data") line.computeLineDistances();
      group.add(line); RG.lines.push({ edge: e, line });
    }
    RG.built = true;
  }
  function pick(e) {
    const { cam, ray } = RG.three, cv = RG.deps.$("#rg-canvas"), b = cv.getBoundingClientRect();
    ray.setFromCamera({ x: (e.clientX - b.left) / b.width * 2 - 1, y: -((e.clientY - b.top) / b.height) * 2 + 1 }, cam);
    const hit = ray.intersectObjects(RG.meshes.map(k => k.mesh), false)[0];
    focus(hit ? RG.meshes.find(k => k.mesh === hit.object).node.id : null);
  }
  function init() {
    if (RG.three) return;
    const THREE = window.THREE, cv = RG.deps.$("#rg-canvas"), r = new THREE.WebGLRenderer({ canvas: cv, antialias: true, alpha: true });
    r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
    scene.add(new THREE.AmbientLight(0xffffff, 0.55)); const dl = new THREE.DirectionalLight(0xffffff, 0.9); dl.position.set(6, 12, 8); scene.add(dl);
    const group = new THREE.Group(); scene.add(group);
    const orbit = { yaw: 0.6, pitch: 0.42, dist: 20, drag: null, target: new THREE.Vector3() };
    cv.addEventListener("pointerdown", e => { if (e.button !== 0) return; orbit.drag = { x: e.clientX, y: e.clientY, moved: false }; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", e => { const d = orbit.drag; if (!d) return;
      orbit.yaw -= (e.clientX - d.x) * 0.006; orbit.pitch = Math.max(-1.2, Math.min(1.2, orbit.pitch + (e.clientY - d.y) * 0.006));
      d.moved = d.moved || Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3; d.x = e.clientX; d.y = e.clientY; });
    cv.addEventListener("pointerup", e => { const d = orbit.drag; orbit.drag = null; if (d && !d.moved) pick(e); });
    cv.addEventListener("wheel", e => { e.preventDefault(); RG.three.goalDist = Math.max(4, Math.min(120, RG.three.goalDist * (e.deltaY > 0 ? 1.1 : 0.9))); }, { passive: false });
    RG.three = { r, scene, cam, group, orbit, ray: new THREE.Raycaster(), goal: new THREE.Vector3(), goalDist: 20 };
    const loop = t => {
      if (!RG.on) { RG.raf = 0; return; }
      const w = cv.clientWidth, h = cv.clientHeight;
      if (w && h && (cv.width !== w || cv.height !== h)) { r.setSize(w, h, false); cam.aspect = w / Math.max(1, h); cam.updateProjectionMatrix(); }
      const o = orbit, T = RG.three;
      o.target.lerp(T.goal, 0.08); o.dist += (T.goalDist - o.dist) * 0.08;
      cam.position.set(o.target.x + o.dist * Math.cos(o.pitch) * Math.sin(o.yaw), o.target.y + o.dist * Math.sin(o.pitch), o.target.z + o.dist * Math.cos(o.pitch) * Math.cos(o.yaw));
      cam.lookAt(o.target);
      for (const k of RG.meshes) {
        const breathe = 1 + 0.03 * Math.sin(t / 900 + k.home.x);
        k.mesh.scale.setScalar(k.pulse ? 1 + 0.16 * Math.sin(t / 180) : (RG.sel === k.node ? 1.12 : breathe));
      }
      group.rotation.y = RG.sel ? group.rotation.y : group.rotation.y + 0.0006;
      r.render(scene, cam);
      RG.raf = requestAnimationFrame(loop);
    };
    RG.loop = loop;
  }
  function ensure() {
    const deps = RG.deps, $ = deps.$;
    if ($("#reportgraph")) return;
    const style = document.createElement("style"); style.textContent = CSS; document.head.append(style);
    document.body.insertAdjacentHTML("beforeend", HTML);
    $("#rg-close").onclick = close;
    $("#rg-shot-tog").onclick = () => slide();
    $("#rg-evidence").onclick = () => { if (RG.request) deps.evidence?.(RG.request.id, RG.image); };
    $("#rg-shot-thumbs").addEventListener("click", e => { const b = e.target.closest("[data-rg-sha]"); if (b) showImage(b.dataset.rgSha); });
    $("#rg-card").addEventListener("click", e => {
      const shot = e.target.closest("[data-rg-shot]"), sub = e.target.closest("[data-rg-open]");
      if (shot) { showImage(shot.dataset.rgShot); slide(true); }
      else if (sub) open(sub.dataset.rgOpen, deps);
      else if (e.target.closest("[data-rg-back]")) focus(null);
    });
    addEventListener("keydown", e => { if (e.key === "Escape" && RG.on && !document.querySelector("#task-evidence.on")) close(); }, true);   // before the evidence popup's own Esc: one press closes one layer
  }
  // deps: { $, esc, api(path), token(), apiUrl(), loadThree(), evidence(requestId, sha), children(requestId), onChange() }
  async function open(requestId, deps) {
    RG.deps = deps; ensure();
    const $ = deps.$, el = $("#reportgraph");
    el.classList.add("on"); RG.on = true; RG.sel = null; deps.onChange?.();
    $("#rg-title").textContent = "Detailed report"; $("#rg-status").textContent = "loading…"; $("#rg-card").hidden = true;
    const r = await deps.api(`/api/requests/${encodeURIComponent(requestId)}`);
    if (!r.ok) { $("#rg-status").textContent = r.error || "Could not load the request"; return null; }
    const x = RG.request = r.data, extra = { children: deps.children?.(x.id) || [] };
    if (x.context?.resolution_chat_id) { const res = await deps.api(`/api/tasks/resolutions/${encodeURIComponent(x.id)}`).catch(() => null); if (res?.ok) extra.resolution = res.data; }
    try {
      const t = await deps.api("/api/tasks?hermes_limit=100"), run = (t.ok ? t.data.hermes || [] : []).find(h => (h.request_ids || []).includes(x.id) || h.request_id === x.id);
      if (run) { const rr = await deps.api(`/api/tasks/hermes/${encodeURIComponent(run.id)}`); extra.run = rr.ok ? { ...run, ...rr.data } : run; }
    } catch {}
    RG.graph = model(x, extra);
    const count = k => RG.graph.nodes.filter(n => n.kind === k).length, plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
    $("#rg-title").textContent = RG.graph.title;
    $("#rg-status").textContent = `${String(x.status || "").replace("_", " ")} · ${plural(count("step"), "subtask")}${count("sub") ? ` · ${plural(count("sub"), "sub-request")}` : ""} · ${plural(count("tool"), "tool")}`;
    shots(x, await deps.token(), extra.children);
    try { await deps.loadThree(); } catch (e) { $("#rg-status").textContent += ` · ${e.message}`; return RG.graph; }
    init(); build(window.THREE); focus(null);
    if (!RG.raf) RG.raf = requestAnimationFrame(RG.loop);
    return RG.graph;
  }
  function close() {
    RG.on = false; if (RG.raf) cancelAnimationFrame(RG.raf); RG.raf = 0;
    RG.deps?.$("#reportgraph")?.classList.remove("on"); RG.deps?.onChange?.();
  }
  return { COLORS, model, layout, cardHtml, statusOf, short, open, close, focus, slide, showImage, state: RG };
})();
