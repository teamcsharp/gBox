'use strict';
/* The decryption lab page. Everything it shows comes from /api/decrypt-lab/state, /api/decrypt-lab/scan and
   /api/decrypt-lab/field through the hardened preload bridge — the page holds no credential and makes no
   network call of its own. */
(() => {
  const api = window.decryptLab;
  const $ = (id) => document.getElementById(id);
  const POLL_MS = 1500;
  const COLORS = {
    code: 0x5b9dd9, data: 0x8f7ad9, heap: 0x4cc4a5, confirmed: 0x79d97a,
    candidate: 0xe0a94a, rejected: 0xd96b6b, zero: 0x2a3442, int: 0xc9d6e4,
    float: 0x86c7e0, ascii: 0xd7c48a, 'pointer?': 0xd8a0d8, raw: 0x8090a0,
  };
  let state = null;
  let selected = null;      // {title, name}
  let lastScan = null;
  let pollTimer = null;

  // ---------------------------------------------------------------- 3D scene
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 500);
  const renderer = new THREE.WebGLRenderer({ canvas: $('scene'), antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const group = new THREE.Group();
  scene.add(group);

  const COLS = 14, ROWS = 8, LAYERS = 4, SIZE = 1.5, GAP = 2.1;
  const blocks = [];
  const geo = new THREE.BoxGeometry(SIZE, SIZE * 0.55, SIZE);
  const edgeGeo = new THREE.EdgesGeometry(geo);
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x1b2a3a, transparent: true, opacity: 0.7 });
  for (let l = 0; l < LAYERS; l++) {
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const mat = new THREE.MeshStandardMaterial({ color: 0x22303f, roughness: 0.55, metalness: 0.25 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set((c - (COLS - 1) / 2) * GAP, (l - (LAYERS - 1) / 2) * 2.2,
                          (r - (ROWS - 1) / 2) * GAP);
        mesh.userData = { index: l * ROWS * COLS + r * COLS + c, kind: 'raw', mat };
        mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));
        group.add(mesh);
        blocks.push(mesh);
      }
    }
  }
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xbfe3ff, 1.15); key.position.set(18, 26, 14); scene.add(key);
  const rim = new THREE.DirectionalLight(0x4cc4a5, 0.5); rim.position.set(-16, -8, -18); scene.add(rim);

  let yaw = -0.6, pitch = 0.72, dist = 46;
  function place() {
    pitch = Math.max(0.18, Math.min(1.45, pitch));
    dist = Math.max(22, Math.min(110, dist));
    camera.position.set(Math.cos(yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist,
                        Math.sin(yaw) * Math.cos(pitch) * dist);
    camera.lookAt(0, 0, 0);
  }
  place();

  let dragging = false, px = 0, py = 0;
  renderer.domElement.addEventListener('pointerdown', (e) => { dragging = true; px = e.clientX; py = e.clientY; });
  window.addEventListener('pointerup', () => { dragging = false; });
  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    yaw += (e.clientX - px) * 0.006;
    pitch -= (e.clientY - py) * 0.005;
    px = e.clientX; py = e.clientY;
    place();
  });
  renderer.domElement.addEventListener('wheel', (e) => { e.preventDefault(); dist *= e.deltaY > 0 ? 1.08 : 0.93; place(); }, { passive: false });

  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
  renderer.domElement.addEventListener('click', (e) => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.intersectObjects(blocks, false)[0];
    if (hit) scanPage(hit.object.userData.index);
  });

  function resize() {
    const el = $('stage');
    const w = el.clientWidth, h = el.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe($('stage'));

  function paint(kindAt) {
    for (const b of blocks) {
      const kind = kindAt(b.userData.index);
      b.userData.kind = kind;
      b.userData.mat.color.setHex(COLORS[kind] || COLORS.raw);
      b.userData.mat.emissive = new THREE.Color(COLORS[kind] || COLORS.raw).multiplyScalar(
        kind === 'confirmed' || kind === 'candidate' ? 0.35 : 0.08);
    }
  }

  (function loop() {
    requestAnimationFrame(loop);
    if (!dragging) group.rotation.y += 0.0012;
    renderer.render(scene, camera);
  })();

  // ---------------------------------------------------------------- data
  const fmtInt = (v) => (typeof v === 'number' ? v.toLocaleString() : v);

  function renderTitles(list) {
    const sel = $('title');
    const keep = sel.value;
    sel.textContent = '';
    for (const t of list) {
      const o = document.createElement('option');
      o.value = t.id; o.textContent = t.id + (t.anchor?.BUILD_ID ? ` · ${t.anchor.BUILD_ID.slice(0, 8)}` : '');
      sel.appendChild(o);
    }
    if (keep && list.some((t) => t.id === keep)) sel.value = keep;
  }

  function currentTitle() {
    const id = $('title').value;
    return state?.titles?.find((t) => t.id === id) || state?.titles?.[0] || null;
  }

  function renderPipeline(t) {
    const body = $('pipeline').querySelector('tbody');
    body.textContent = '';
    if (!t) return;
    for (const [stage, row] of Object.entries(t.stages)) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${t.id}</td><td>${stage}</td>
        <td><span class="dot ${row.done ? 'on' : 'off'}"></span>${escapeHtml(row.detail || '')}</td>`;
      body.appendChild(tr);
    }
  }

  function renderFields(t) {
    const body = $('fields').querySelector('tbody');
    body.textContent = '';
    $('field-count').textContent = '';
    if (!t) return;
    const counts = { confirmed: 0, candidate: 0, rejected: 0 };
    for (const f of t.fields) {
      counts[f.status] = (counts[f.status] || 0) + 1;
      const tr = document.createElement('tr');
      tr.className = 'click' + (selected && selected.title === t.id && selected.name === f.name ? ' sel' : '');
      tr.innerHTML = `<td>${escapeHtml(f.name)}</td><td>${escapeHtml(String(f.offset))}</td>
        <td class="muted">${escapeHtml(f.kind || '')}</td>
        <td><span class="badge ${f.status}">${f.status}</span></td>`;
      tr.addEventListener('click', () => {
        selected = { title: t.id, name: f.name };
        $('evidence').textContent = f.evidence || 'no evidence recorded';
        renderFields(t);
      });
      body.appendChild(tr);
    }
    $('field-count').textContent = `${counts.confirmed} confirmed · ${counts.candidate} candidate · ${counts.rejected} rejected`;
  }

  function renderBot(bot) {
    const el = $('bot');
    el.textContent = '';
    if (!bot || !bot.sessions?.length) {
      el.innerHTML = '<p class="muted">No live tactical frame right now.</p>';
      return;
    }
    const s = bot.sessions[0];
    const dl = document.createElement('dl');
    const rows = [
      ['session', s.session], ['live', s.live ? `yes (${s.age_s}s old)` : `no (${s.age_s}s)`],
      ['stage', s.stage || '—'], ['round', s.round ? JSON.stringify(s.round) : '—'],
      ['player', s.player ? JSON.stringify(s.player) : '—'],
      ['aim', s.aim ? JSON.stringify(s.aim) : '—'],
      ['units', s.units ? `${(Array.isArray(s.units) ? s.units.length : Object.keys(s.units).length)} visible` : '—'],
      ['frame keys', (s.keys || []).join(', ')],
    ];
    for (const [k, v] of rows) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = String(v);
      dl.append(dt, dd);
    }
    el.appendChild(dl);
  }

  function renderEvents(events) {
    const el = $('events');
    el.textContent = '';
    for (const e of [...(events || [])].reverse().slice(0, 40)) {
      const li = document.createElement('li');
      li.innerHTML = `<span class="t">${new Date(e.at * 1000).toLocaleTimeString()}</span>
        <span class="k">${escapeHtml(e.kind)}</span>${escapeHtml(e.text)}`;
      el.appendChild(li);
    }
  }

  const KIND_LABEL = {
    model: 'model', texture: 'texture', audio: 'audio', video: 'video', font: 'font',
    data: 'data', archive: 'archive', other: 'other',
  };
  function kindLabel(path) {
    const ext = (path.match(/\.([a-z0-9]+)$/i) || [, ''])[1].toLowerCase();
    const map = {
      mod: 'model', mesh: 'model', smd: 'model', dae: 'model', tex: 'texture', png: 'texture',
      dds: 'texture', tga: 'texture', jpg: 'texture', bmp: 'texture', ogg: 'audio', wav: 'audio',
      sngw: 'audio', at9: 'audio', adx: 'audio', sfx: 'audio', mca: 'audio', arc: 'archive',
      pkg: 'archive', pak: 'archive', bnk: 'archive', sbnk: 'archive', dat: 'archive',
      json: 'data', xml: 'data', txt: 'data', csv: 'data',
    };
    return map[ext] || 'other';
  }
  function fmtBytes(n) {
    if (!Number.isFinite(n)) return '—';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  }
  function toBase64(bytes) {
    let out = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(out);
  }

  async function loadAssets() {
    const t = currentTitle();
    if (!t) return;
    const q = $('asset-q').value.trim();
    const kind = $('asset-kind').value;
    try {
      const data = await api.api(`/api/decrypt-lab/assets?title=${encodeURIComponent(t.id)}`
        + `&kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`);
      renderAssets(data);
    } catch (err) {
      $('extract-meta').textContent = String(err.message || err).slice(0, 90);
    }
  }

  function renderAssets(data) {
    const body = $('assets').querySelector('tbody');
    body.textContent = '';
    if (!data.inventory) {
      $('extract-meta').textContent = 'no RomFS inventory';
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="3" class="muted">${escapeHtml(data.note || 'no inventory yet')}</td>`;
      body.appendChild(tr);
      return;
    }
    const counts = data.counts || {};
    $('extract-meta').textContent = `${data.total} files · `
      + Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(' · ');
    for (const e of data.entries) {
      const tr = document.createElement('tr');
      tr.className = 'click';
      tr.innerHTML = `<td title="${escapeHtml(e.path)}">${escapeHtml(e.path)}</td>`
        + `<td class="muted">${kindLabel(e.path)}</td><td>${fmtBytes(e.size)}</td>`;
      tr.addEventListener('click', () => {
        $('stage-path').value = e.path;
        showPreview(e.path);
      });
      body.appendChild(tr);
    }
  }

  async function showPreview(path) {
    const t = currentTitle();
    const img = $('preview-img');
    const note = $('preview-note');
    img.classList.remove('shown');
    img.removeAttribute('src');
    if (!t) return;
    note.textContent = `previewing ${path}…`;
    try {
      const r = await api.preview(t.id, path);
      img.src = r.dataUrl;
      img.classList.add('shown');
      note.textContent = `${path} · ${(r.bytes / 1024).toFixed(0)} KiB`;
    } catch (err) {
      const msg = String(err.message || err);
      note.textContent = msg.replace(/^Error invoking remote method '[^']+':\s*/, '').slice(0, 140);
    }
  }

  async function stageReplacement() {
    const t = currentTitle();
    const file = $('stage-file').files[0];
    const path = $('stage-path').value.trim();
    if (!t || !file || !path) {
      $('stage-status').textContent = 'choose a title, a file and a RomFS path';
      return;
    }
    $('stage-status').textContent = `reading ${file.name}…`;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const r = await api.api('/api/decrypt-lab/stage',
        { title: t.id, path, data_b64: toBase64(bytes), build: 'gbox-lab' }, 'POST');
      $('stage-status').textContent = `staged ${r.size} bytes → ${r.target}`;
      await loadState();
    } catch (err) {
      $('stage-status').textContent = String(err.message || err).slice(0, 140);
    }
  }

  async function swapEntry() {
    const t = currentTitle();
    const arc = $('swap-arc').value.trim();
    const entry = $('swap-entry').value.trim();
    const donorArc = $('swap-donor-arc').value.trim();
    const donorEntry = $('swap-donor-entry').value.trim();
    const build = ($('swap-build').value.trim() || 'gbox-lab');
    if (!t || !arc || !entry || !donorArc || !donorEntry) {
      $('swap-status').textContent = 'give the archive, its entry, and the donor archive and entry';
      return;
    }
    $('swap-status').textContent = `swapping ${entry}…`;
    try {
      const r = await api.api('/api/decrypt-lab/arc-swap',
        { title: t.id, arc_path: arc, entry, donor_arc: donorArc, donor_entry: donorEntry, build }, 'POST');
      $('swap-status').textContent =
        `swapped ${r.entry_bytes} bytes into ${r.target} (applies at next boot)`;
      await loadState();
    } catch (err) {
      $('swap-status').textContent = String(err.message || err).slice(0, 160);
    }
  }

  function renderHex(scan) {    const el = $('hex');
    el.textContent = '';
    $('scan-meta').textContent = scan ? `${scan.length} bytes @ 0x${scan.addr.toString(16)} · ${JSON.stringify(scan.counts)}` : '';
    if (!scan) { el.innerHTML = '<p class="muted">Press Scan to read guest memory.</p>'; return; }
    for (let i = 0; i < scan.cells.length; i += 4) {
      const row = document.createElement('div');
      row.className = 'row';
      const cells = scan.cells.slice(i, i + 4);
      const addr = document.createElement('span');
      addr.className = 'addr';
      addr.textContent = '0x' + cells[0].addr.toString(16);
      row.appendChild(addr);
      for (const c of cells) {
        const span = document.createElement('span');
        span.className = 'cell';
        span.dataset.kind = c.kind;
        span.textContent = c.hex;
        span.title = `${c.kind} · int ${c.int} · u ${c.u}${c.f !== null ? ' · f ' + c.f : ''}`;
        row.appendChild(span);
      }
      const asc = document.createElement('span');
      asc.className = 'ascii';
      asc.textContent = cells.map((c) => c.ascii).join(' ');
      row.appendChild(asc);
      el.appendChild(row);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------------------------------------------------------------- actions
  async function loadState() {
    try {
      const next = await api.api('/api/decrypt-lab/state');
      state = next;
      $('status').textContent = next.emulator ? 'emulator attached' : 'no emulator';
      renderTitles(next.titles || []);
      const t = currentTitle();
      renderPipeline(t);
      renderFields(t);
      renderBot(next.bot);
      renderEvents(next.events);
      loadAssets();
      // colour the lattice: confirmed/candidate fields, then scan kinds
      paint((i) => {
        const conf = t?.fields?.filter((f) => f.status === 'confirmed').length || 0;
        const cand = t?.fields?.filter((f) => f.status === 'candidate').length || 0;
        const rej = t?.fields?.filter((f) => f.status === 'rejected').length || 0;
        if (i < conf) return 'confirmed';
        if (i < conf + cand) return 'candidate';
        if (i < conf + cand + rej) return 'rejected';
        return lastScan?.cells ? lastScan.cells[i % lastScan.cells.length]?.kind || 'raw' : 'raw';
      });
    } catch (err) {
      $('status').textContent = String(err.message || err).slice(0, 80);
    }
  }

  async function scanPage(index) {
    const t = currentTitle();
    if (!t) return;
    $('status').textContent = `scanning page ${index}…`;
    try {
      const scan = await api.api('/api/decrypt-lab/scan', { title: t.id, offset: index * 0x100, length: 256, mode: 'module' }, 'POST');
      lastScan = scan;
      renderHex(scan);
      $('status').textContent = `scanned 0x${scan.addr.toString(16)}`;
      await loadState();
    } catch (err) {
      $('status').textContent = String(err.message || err).slice(0, 90);
    }
  }

  $('refresh').addEventListener('click', loadState);
  $('scan').addEventListener('click', () => scanPage(0));
  $('title').addEventListener('change', () => { const t = currentTitle(); renderPipeline(t); renderFields(t); loadAssets(); });
  $('asset-q').addEventListener('input', loadAssets);
  $('asset-kind').addEventListener('change', loadAssets);
  $('stage-go').addEventListener('click', stageReplacement);
  $('swap-go').addEventListener('click', swapEntry);
  $('top').addEventListener('change', () => api.alwaysOnTop($('top').checked));

  api.info().then((info) => {
    $('top').checked = info.top === true;
    $('subtitle').textContent = `one pipeline, every title · ${info.origin || ''}`;
  }).catch(() => {});
  api.onScope?.((scope) => { $('subtitle').textContent = `one pipeline, every title · ${scope.origin || ''}`; });

  resize();
  loadState();
  pollTimer = setInterval(() => { if (!document.hidden) loadState(); }, POLL_MS);
  window.addEventListener('beforeunload', () => clearInterval(pollTimer));
})();
