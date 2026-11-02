// Spark2 task dashboard renderer. Loads the aggregated Hermes feed over the preload's read-only IPC
// proxy (no credential in this window, CSP default-src 'none'), draws an interactive Three.js scene
// (a 3D donut of tasks-by-state + a bubble field of tasks-by-node sized by tokens) and a live tray of
// task cards that slide/shuffle as runs enter, run and complete. Clicking a card expands it to show the
// tool-by-tool trace, the responses, the correspondence and any images — lazily fetched on expand.
// THREE is the global from vendor/three.min.js (UMD) — a classic script, so ES-module imports (blocked
// over file:// in the Electron popup) are avoided, matching how the Mercenaries window loads its scripts.
(function () {
'use strict';
const THREE = window.THREE;
const bridge = window.taskWindow;
const $ = sel => document.querySelector(sel);

// ---- palette (dataviz dark steps) -----------------------------------------
const css = getComputedStyle(document.body);
const col = name => (css.getPropertyValue(name) || '').trim() || '#888';
const C = {
  running: col('--running'), good: col('--good'), warning: col('--warning'), critical: col('--critical'),
  surface: col('--surface-1'), grid: col('--grid'), text: col('--text-secondary'),
  nodes: ['--s-blue', '--s-orange', '--s-aqua', '--s-yellow', '--s-magenta', '--s-green', '--s-violet', '--s-red'].map(col)
};
const STATES = [
  { key: 'running',   label: 'In flight', color: C.running },
  { key: 'claimed',   label: 'Queued',    color: C.warning },
  { key: 'completed', label: 'Done',      color: C.good },
  { key: 'failed',    label: 'Failed',    color: C.critical }
];
const STATE_LABEL = Object.fromEntries(STATES.map(s => [s.key, s.label]));
const STATE_COLOR = Object.fromEntries(STATES.map(s => [s.key, s.color]));

function stateClass(s) {
  s = (s || '').toLowerCase();
  if (s === 'running') return 'running';
  if (s === 'completed' || s === 'succeeded' || s === 'success' || s === 'done') return 'completed';
  if (s === 'failed' || s === 'error' || s === 'cancelled' || s === 'canceled') return 'failed';
  return 'claimed';                    // claimed / queued / pending / anything unknown-but-live
}
function nodeOf(run) { return run.provider || run.billing_provider || run.model || 'local'; }
function tokensOf(run) { return (run.tokens_in || 0) + (run.tokens_out || 0); }
function titleOf(run) {
  const t = (run.tickets && run.tickets[0]) || null;
  if (t && t.title) return (t.number ? '#' + t.number + ' ' : '') + t.title;
  return run.name || run.job_id || run.id.slice(0, 8);
}
const num = n => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n)));
function ago(t) {
  if (!t) return '';
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return Math.round(s) + 's';
  if (s < 3600) return Math.round(s / 60) + 'm';
  return Math.round(s / 3600) + 'h';
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

// Running tasks have no server-reported percentage: creep a bar toward ~90% with elapsed time so it reads
// as working; the detail view (when loaded) refines it to the finished-step ratio. Terminal states snap.
function progressOf(run, detail) {
  const cls = stateClass(run.state);
  if (cls === 'completed') return 1;
  if (cls === 'failed') return 1;
  if (detail && Array.isArray(detail.steps) && detail.steps.length) {
    const done = detail.steps.filter(s => s.status !== 'running').length;
    return Math.max(0.08, Math.min(0.97, (done + 0.5) / (detail.steps.length + 0.5)));
  }
  if (cls === 'running' && run.started) {
    const min = (Date.now() / 1000 - run.started) / 60;
    return 0.1 + 0.8 * (1 - 1 / (1 + min));
  }
  return 0.05;
}

// ---------------------------------------------------------------------------
let origin = '';
let data = { runs: [] };
const detailCache = new Map();        // run id -> {steps, output, request}
const cardEls = new Map();            // run id -> element
let expandedId = null;
let pollTimer = null, pollMs = 1100, failStreak = 0;

async function apiGet(path) {
  const r = await bridge.api(path);
  return r;
}

// ---- data polling with graceful degradation -------------------------------
async function poll() {
  try {
    let feed;
    try {
      feed = await apiGet('/api/hermes/dashboard?limit=24');
    } catch (e) {
      // Before the 05:00 restart the new endpoint is absent; fall back to the existing /api/tasks feed.
      if (e && e.status === 404) feed = await apiGet('/api/tasks?hermes_limit=24');
      else throw e;
    }
    data = {
      runs: feed.runs || feed.hermes || [],
      providers: feed.providers || null,
      local: feed.local || null,
      grunt: feed.grunt || (feed.providers && feed.providers.grunt) || null,
      queue: feed.queue || null
    };
    failStreak = 0;
    setConn('live', 'Live');
    render();
  } catch (e) {
    failStreak++;
    setConn(failStreak > 2 ? 'error' : 'connecting', failStreak > 2 ? 'Reconnecting…' : 'Connecting…');
  } finally {
    pollTimer = setTimeout(poll, pollMs);
  }
}
function setConn(cls, text) {
  const el = $('#conn'); el.className = 'conn ' + cls; el.textContent = text;
}

// ---- top render ------------------------------------------------------------
function render() {
  const runs = data.runs.slice();
  renderTiles(runs);
  renderLegend(runs);
  renderNodes(runs);
  renderTray(runs);
  scene.update(runs);
}

function renderTiles(runs) {
  const counts = { running: 0, claimed: 0, completed: 0, failed: 0 };
  let tokens = 0, lastHr = 0;
  const nowS = Date.now() / 1000;
  for (const r of runs) {
    counts[stateClass(r.state)]++;
    tokens += tokensOf(r);
    if (r.finished && nowS - r.finished < 3600 && stateClass(r.state) !== 'running') lastHr++;
  }
  const lanes = laneUse(runs);
  const tiles = [
    { label: 'In flight', value: counts.running, color: C.running, max: Math.max(1, runs.length) },
    { label: 'Done / hr', value: lastHr, unit: 'runs', color: C.good },
    { label: 'Tokens (shown)', value: num(tokens), color: C.warning, raw: true },
    { label: 'Lanes in use', value: lanes.used, unit: '/ ' + lanes.total, color: C.running, max: lanes.total || 1, barVal: lanes.used }
  ];
  $('#tiles').innerHTML = tiles.map(t => `
    <div class="tile">
      <div class="label">${esc(t.label)}</div>
      <div class="value">${t.raw ? esc(t.value) : esc(String(t.value))}${t.unit ? `<span class="unit">${esc(t.unit)}</span>` : ''}</div>
      ${t.max ? `<div class="spark"><span style="width:${Math.round(100 * (t.barVal != null ? t.barVal : t.value) / t.max)}%;background:${t.color}"></span></div>` : ''}
    </div>`).join('');
}

function laneUse(runs) {
  // Lanes = providers/nodes currently serving a running task, against the provider capacity when known.
  const active = new Set(runs.filter(r => stateClass(r.state) === 'running').map(nodeOf));
  let total = 0;
  const p = data.providers;
  if (p && Array.isArray(p.routes)) for (const r of p.routes) total += Number(r.lanes || r.concurrency || 0) || 0;
  return { used: active.size, total: total || active.size };
}

function renderLegend(runs) {
  const counts = {}; for (const r of runs) { const k = stateClass(r.state); counts[k] = (counts[k] || 0) + 1; }
  $('#legend').innerHTML = STATES.map(s =>
    `<span class="item"><span class="swatch" style="background:${s.color}"></span>${esc(s.label)} ${counts[s.key] || 0}</span>`).join('');
}

function renderNodes(runs) {
  const map = new Map();
  for (const r of runs) {
    const n = nodeOf(r); const e = map.get(n) || { name: n, running: 0, total: 0, tokens: 0 };
    e.total++; e.tokens += tokensOf(r); if (stateClass(r.state) === 'running') e.running++;
    map.set(n, e);
  }
  const nodes = [...map.values()].sort((a, b) => b.running - a.running || b.total - a.total).slice(0, 6);
  const colorFor = n => C.nodes[[...map.keys()].indexOf(n) % C.nodes.length];
  $('#nodes').innerHTML = nodes.map(n => {
    const spark = n.total ? Math.round(100 * n.running / n.total) : 0;
    const c = colorFor(n.name);
    return `<div class="node">
      <div class="n-name"><span class="dot" style="background:${c}"></span>${esc(n.name)}</div>
      <div class="n-meta">${n.running} running · ${n.total} runs · ${num(n.tokens)} tok</div>
      <div class="lanes"><span style="width:${spark}%;background:${c}"></span></div>
    </div>`;
  }).join('') || '<div class="muted">No active nodes.</div>';
}

// ---- the live tray (FLIP: cards slide/shuffle on reorder, enter and leave) -
const ROW_GAP = 8;
function renderTray(runs) {
  const tray = $('#tray');
  $('#count').textContent = runs.length ? '(' + runs.length + ')' : '';
  $('#empty').hidden = runs.length > 0;
  const live = new Set(runs.map(r => r.id));

  // remove cards whose run is gone
  for (const [id, el] of cardEls) {
    if (!live.has(id)) {
      el.classList.add('leave');
      cardEls.delete(id);
      if (expandedId === id) expandedId = null;
      setTimeout(() => el.remove(), 340);
    }
  }
  // create/update
  const byId = new Map(runs.map(r => [r.id, r]));
  for (const run of runs) {
    let el = cardEls.get(run.id);
    if (!el) {
      el = buildCard(run);
      cardEls.set(run.id, el);
      tray.appendChild(el);
      el.classList.add('enter');
      requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove('enter')));
    } else {
      updateCard(el, run);
    }
  }
  // layout: position every card by its index with a transform so order changes animate
  let y = 0;
  runs.forEach(run => {
    const el = cardEls.get(run.id);
    if (!el) return;
    el.style.transform = `translateY(${y}px)`;
    const h = el.offsetHeight || 78;
    y += h + ROW_GAP;
  });
  tray.style.height = y + 'px';
  // keep expanded card detail fresh
  if (expandedId && byId.has(expandedId)) refreshDetail(expandedId);
}

function buildCard(run) {
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.id = run.id;
  el.addEventListener('click', ev => { if (!ev.target.closest('.detail')) toggleCard(run.id); });
  updateCard(el, run);
  return el;
}

function cardMarkup(run, detail) {
  const cls = stateClass(run.state);
  const node = nodeOf(run);
  const pct = Math.round(progressOf(run, detail) * 100);
  const tok = tokensOf(run);
  const sub = (run.progress || '').slice(0, 100) || (run.error ? 'Error: ' + run.error.slice(0, 80) : STATE_LABEL[cls]);
  return `
    <div class="c-top">
      <span class="c-title" title="${esc(titleOf(run))}">${esc(titleOf(run))}</span>
      <span class="badge node" title="node / provider">${esc(node)}</span>
      <span class="state-chip">${esc(STATE_LABEL[cls])}</span>
    </div>
    <div class="c-sub">${esc(sub)}${run.model ? ' · ' + esc(run.model) : ''}${tok ? ' · ' + num(tok) + ' tok' : ''}${run.started ? ' · ' + ago(run.started) + ' ago' : ''}</div>
    <div class="prog"><span style="width:${pct}%"></span></div>`;
}

function updateCard(el, run) {
  const cls = stateClass(run.state);
  el.className = 'card state-' + cls + (expandedId === run.id ? ' expanded' : '');
  const detail = detailCache.get(run.id);
  const head = cardMarkup(run, detail);
  let detailEl = el.querySelector('.detail');
  el.innerHTML = head + (expandedId === run.id ? '<div class="detail"></div>' : '');
  if (expandedId === run.id) renderDetail(el.querySelector('.detail'), run, detailCache.get(run.id));
}

function toggleCard(id) {
  expandedId = expandedId === id ? null : id;
  const run = data.runs.find(r => r.id === id);
  if (expandedId === id && run) fetchDetail(id, run);
  // re-render all cards (expand/collapse changes heights → relayout)
  for (const [rid, el] of cardEls) { const r = data.runs.find(x => x.id === rid); if (r) updateCard(el, r); }
  // relayout after the DOM settles
  requestAnimationFrame(() => renderTray(data.runs));
}

// ---- per-card detail: tools, responses, correspondence, images ------------
async function fetchDetail(id, run) {
  try {
    const detail = await apiGet('/api/tasks/hermes/' + id);
    const entry = { steps: detail.steps || [], output: detail.output || '', request: null, request_id: detail.request_id || (run.request_ids || [])[0] || null };
    detailCache.set(id, entry);
    if (entry.request_id) {
      try {
        const req = await apiGet('/api/requests/' + entry.request_id);
        entry.request = req;
      } catch {}
    }
    if (expandedId === id) { const el = cardEls.get(id); if (el) { updateCard(el, run); requestAnimationFrame(() => renderTray(data.runs)); } }
  } catch {}
}
let lastRefresh = 0;
function refreshDetail(id) {
  // light refresh of the open run's trace while it runs (throttled)
  const now = Date.now();
  if (now - lastRefresh < 1400) return; lastRefresh = now;
  const run = data.runs.find(r => r.id === id);
  if (run && stateClass(run.state) === 'running') fetchDetail(id, run);
}

function renderDetail(host, run, detail) {
  if (!host) return;
  if (!detail) { host.innerHTML = '<div class="loading">Loading the task trace…</div>'; return; }
  const steps = detail.steps || [];
  const toolsHtml = steps.length ? steps.map(s => {
    const arg = s.input ? JSON.stringify(s.input).slice(0, 140) : '';
    return `<div class="step ${esc(s.status || '')}">
      <span class="tool">${esc((s.action || 'tool').replace('mcp__gbox__', ''))}${s.attempt > 1 ? ' #' + s.attempt : ''}</span>
      <span class="s-arg" title="${esc(arg)}">${esc(arg)}</span>
      <span class="s-mark">${s.status === 'finished' ? '✓' : s.status === 'failed' ? '✕' : '…'}</span>
    </div>`;
  }).join('') : '<div class="muted">No tool calls recorded yet.</div>';

  const tickets = (run.tickets || []).map(t => `<span class="badge">#${esc(t.number || '')} ${esc((t.title || '').slice(0, 40))}</span>`).join(' ');

  // correspondence + images from the linked request
  let msgHtml = '', imgHtml = '';
  const req = detail.request;
  if (req && Array.isArray(req.messages) && req.messages.length) {
    const msgs = req.messages.slice(-6);
    msgHtml = msgs.map(m => {
      const atts = (m.attachments || []).filter(a => /^image\//.test(a.type || '') && a.sha256);
      const chips = atts.map(a => `<button class="imgchip" data-sha="${esc(a.sha256)}">${esc(a.name || 'image')} ↗</button>`).join(' ');
      return `<div class="msg"><div class="who">${esc(m.author || m.role || 'msg')}</div>
        <div class="body">${esc((m.text || '').slice(0, 600))}</div>${chips ? '<div class="imgs">' + chips + '</div>' : ''}</div>`;
    }).join('');
  }

  const respText = (detail.output || '').slice(-6000) || 'No output emitted yet.';

  host.innerHTML = `
    <div class="d-section"><div class="d-head">Tools deployed (${steps.length})</div>${toolsHtml}</div>
    ${tickets ? `<div class="d-section"><div class="d-head">Tickets</div>${tickets}</div>` : ''}
    ${msgHtml ? `<div class="d-section"><div class="d-head">Correspondence</div>${msgHtml}</div>` : ''}
    <div class="d-section"><div class="d-head">Latest responses</div><pre class="resp">${esc(respText)}</pre></div>`;

  // wire image chips: fetch bytes over IPC (CSP blocks remote <img>), swap to a data: URL
  host.querySelectorAll('.imgchip').forEach(btn => {
    btn.addEventListener('click', async ev => {
      ev.stopPropagation();
      const sha = btn.dataset.sha;
      btn.textContent = 'loading…';
      try {
        const url = await bridge.image(sha);
        const img = document.createElement('img');
        img.src = url; img.alt = 'attachment';
        img.addEventListener('click', () => lightbox(url));
        btn.replaceWith(img);
      } catch (e) { btn.textContent = 'image unavailable'; }
    });
  });
}

function lightbox(url) {
  const box = document.createElement('div'); box.id = 'lightbox';
  const img = document.createElement('img'); img.src = url; box.appendChild(img);
  box.addEventListener('click', () => box.remove());
  document.body.appendChild(box);
}

// ---- Three.js scene: 3D donut (by state) + bubble field (by node) ----------
const scene = (() => {
  const canvas = $('#stage'), wrap = $('#stage-wrap'), hoverEl = $('#hover');
  let renderer, cam, sceneObj, root, pieGroup, bubbleGroup, raycaster, pointer = { x: -2, y: -2, has: false };
  let ok = false, sig = '', bubbles = [], segs = [];

  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setClearColor(0x000000, 0);
    const sc = sceneObj = new THREE.Scene();
    cam = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    cam.position.set(0, 1.9, 8.2); cam.lookAt(0, 0, 0);
    sc.add(new THREE.AmbientLight(0xffffff, 0.85));
    const key = new THREE.DirectionalLight(0xffffff, 0.9); key.position.set(3, 6, 5); sc.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.4); rim.position.set(-4, 2, -3); sc.add(rim);
    root = new THREE.Group(); sc.add(root);
    pieGroup = new THREE.Group(); pieGroup.position.set(-2.7, 0, 0); pieGroup.rotation.x = -0.62; root.add(pieGroup);
    bubbleGroup = new THREE.Group(); bubbleGroup.position.set(2.2, 0, 0); root.add(bubbleGroup);
    raycaster = new THREE.Raycaster();
    ok = true;
    scene_resize();
    window.addEventListener('resize', scene_resize);
    canvas.addEventListener('pointermove', e => {
      const r = canvas.getBoundingClientRect();
      pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1; pointer.has = true;
      hoverEl.style.left = Math.min(e.clientX - r.left + 12, r.width - 230) + 'px';
      hoverEl.style.top = (e.clientY - r.top + 12) + 'px';
    });
    canvas.addEventListener('pointerleave', () => { pointer.has = false; hoverEl.hidden = true; });
    canvas.addEventListener('click', onClick);
    requestAnimationFrame(loop);
  } catch (e) {
    wrap.innerHTML = '<div class="muted" style="padding:16px">3D view unavailable here — the tray and analytics still update live.</div>';
  }

  function scene_resize() {
    if (!ok) return;
    const w = wrap.clientWidth || 400, h = wrap.clientHeight || 260;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
  }

  // annular-sector extruded segment
  function segMesh(a0, a1, color, height, rOut = 1.5, rIn = 0.78) {
    const shape = new THREE.Shape();
    const steps = Math.max(2, Math.round((a1 - a0) / 0.12));
    shape.absarc(0, 0, rOut, a0, a1, false);
    shape.absarc(0, 0, rIn, a1, a0, true);
    const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.03, bevelSegments: 1, steps: 1, curveSegments: steps });
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.55, metalness: 0.1, emissive: new THREE.Color(color), emissiveIntensity: 0.12 });
    return new THREE.Mesh(geo, mat);
  }

  function rebuildPie(counts) {
    segs.forEach(s => { s.mesh.geometry.dispose(); s.mesh.material.dispose(); pieGroup.remove(s.mesh); });
    segs = [];
    const total = STATES.reduce((a, s) => a + (counts[s.key] || 0), 0);
    let a = 0;
    if (!total) { // placeholder ring
      const m = segMesh(0, Math.PI * 2, C.grid, 0.18); pieGroup.add(m); segs.push({ mesh: m, state: null, count: 0 }); return;
    }
    for (const s of STATES) {
      const n = counts[s.key] || 0; if (!n) continue;
      const frac = n / total, a1 = a + frac * Math.PI * 2;
      const height = s.key === 'running' ? 0.55 : 0.3;
      const m = segMesh(a + 0.01, a1 - 0.01, s.color, height);
      pieGroup.add(m); segs.push({ mesh: m, state: s, count: n, frac });
      a = a1;
    }
  }

  function rebuildBubbles(runs) {
    bubbles.forEach(b => { b.mesh.geometry.dispose(); b.mesh.material.dispose(); bubbleGroup.remove(b.mesh); });
    bubbles = [];
    const nodes = [...new Set(runs.map(nodeOf))];
    const maxTok = Math.max(1, ...runs.map(tokensOf));
    runs.forEach((run, i) => {
      const lane = nodes.indexOf(nodeOf(run));
      const r = 0.12 + 0.34 * Math.sqrt(tokensOf(run) / maxTok);
      const geo = new THREE.SphereGeometry(r, 20, 16);
      const color = STATE_COLOR[stateClass(run.state)];
      const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.35, metalness: 0.15, emissive: new THREE.Color(color), emissiveIntensity: stateClass(run.state) === 'running' ? 0.4 : 0.15 });
      const mesh = new THREE.Mesh(geo, mat);
      const col = nodes.length > 1 ? (lane / (nodes.length - 1) - 0.5) * 2.6 : 0;
      const hash = [...run.id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
      mesh.position.set(col, ((hash % 100) / 100 - 0.5) * 2.6, ((hash >> 7) % 100) / 100 * 0.8 - 0.4);
      mesh.userData = { run, phase: (hash % 628) / 100, baseY: mesh.position.y };
      bubbleGroup.add(mesh); bubbles.push({ mesh, run });
    });
  }

  function onClick() {
    if (!ok || !pointer.has) return;
    raycaster.setFromCamera(pointer, cam);
    const hit = raycaster.intersectObjects(bubbleGroup.children, false)[0];
    if (hit && hit.object.userData.run) {
      const id = hit.object.userData.run.id;
      if (expandedId !== id) toggleCard(id);
      const el = cardEls.get(id); if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function hover() {
    if (!ok || !pointer.has) { hoverEl.hidden = true; return; }
    raycaster.setFromCamera(pointer, cam);
    const b = raycaster.intersectObjects(bubbleGroup.children, false)[0];
    if (b && b.object.userData.run) {
      const run = b.object.userData.run;
      hoverEl.hidden = false;
      hoverEl.innerHTML = `<div class="h-title">${esc(titleOf(run))}</div>
        <div class="h-row">${esc(nodeOf(run))} · ${esc(STATE_LABEL[stateClass(run.state)])}</div>
        <div class="h-row">${num(tokensOf(run))} tokens${run.model ? ' · ' + esc(run.model) : ''}</div>`;
      return;
    }
    const s = raycaster.intersectObjects(pieGroup.children, false)[0];
    if (s) {
      const seg = segs.find(x => x.mesh === s.object);
      if (seg && seg.state) {
        hoverEl.hidden = false;
        hoverEl.innerHTML = `<div class="h-title">${esc(seg.state.label)}</div><div class="h-row">${seg.count} task${seg.count === 1 ? '' : 's'}</div>`;
        return;
      }
    }
    hoverEl.hidden = true;
  }

  function loop(t) {
    if (!ok) return;
    requestAnimationFrame(loop);
    pieGroup.rotation.z = (pieGroup.rotation.z || 0) + 0.0016;
    const sec = t / 1000;
    for (const b of bubbles) {
      b.mesh.position.y = b.mesh.userData.baseY + Math.sin(sec * 1.1 + b.mesh.userData.phase) * 0.09;
      if (stateClass(b.run.state) === 'running') { const s = 1 + Math.sin(sec * 3 + b.mesh.userData.phase) * 0.06; b.mesh.scale.setScalar(s); }
    }
    hover();
    renderer.render(sceneObj, cam);
  }

  function update(runs) {
    if (!ok) return;
    const counts = {}; for (const r of runs) counts[stateClass(r.state)] = (counts[stateClass(r.state)] || 0) + 1;
    const newSig = runs.map(r => r.id + stateClass(r.state) + tokensOf(r) + nodeOf(r)).join('|');
    if (newSig !== sig) { sig = newSig; rebuildPie(counts); rebuildBubbles(runs); }
  }
  return { update };
})();

// ---- window chrome ---------------------------------------------------------
async function init() {
  try { const info = await bridge.info(); origin = info.origin; $('#top').checked = !!info.top; }
  catch {}
  bridge.onScope(s => { origin = s.origin; $('#top').checked = !!s.top; });
  $('#top').addEventListener('change', e => bridge.alwaysOnTop(e.target.checked));
  document.addEventListener('visibilitychange', () => { pollMs = document.hidden ? 4000 : 1100; });
  window.addEventListener('keydown', e => { if (e.key === 'Escape') { const lb = $('#lightbox'); if (lb) lb.remove(); } });
  poll();
}
init();
})();
