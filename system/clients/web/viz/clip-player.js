// Animation clips in the model view (#1384). Shared by the web client's model view (also the desktop app's embedded
// library page) and the desktop shell's 3D cards. A collection entry lists its clips in meta.animations:
//   3D {name, duration_s, source, file, drives}  file = the GLB holding it (the model itself, or <slug>.anims.glb whose
//      node names match the model's skeleton); drives "controls" = native control curves on helper nodes (DOA2 MOT),
//      which do not move the mesh: the bars show their values instead.
//   2D sprite_capture clips {clip, name, preview (APNG), webp, mp4, frames, fps}.
// Plays 3D clips with THREE.AnimationMixer (THREE is passed in: no import here), time driven by GBoxClips.step.
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const SPEEDS = [0.25, 0.5, 1, 1.5, 2];
  const isSprite = a => a && ('clip' in a || 'sheet' in a);
  const fmt = t => (Math.max(0, +t || 0)).toFixed(2) + ' s';

  // meta.animations + the clips the loaded GLB embeds ([{name, duration}]) -> one list of rows
  function list(meta, embedded = []) {
    const rows = (meta && meta.animations) || [];
    if ((meta && meta.kind === 'sprites') || rows.some(isSprite))
      return rows.filter(isSprite).map(a => ({ kind: '2d', name: a.name || a.clip, clip: a.clip, preview: a.webp || a.preview,
        apng: a.preview || null, webp: a.webp || null, mp4: a.mp4 || null, frames: a.frames || 0, fps: a.fps || 0,
        duration: a.frames && a.fps ? a.frames / a.fps : 0 }));
    const out = [], seen = new Set();
    for (const a of rows) {
      if (!a || !a.name) continue;
      const file = a.file || (meta && meta.model) || '';
      if (seen.has(file + '\n' + a.name)) continue;
      seen.add(file + '\n' + a.name);
      out.push({ kind: '3d', name: a.name, duration: +a.duration_s || 0, file, drives: a.drives || 'skeleton', source: a.source || '' });
    }
    const model = (meta && meta.model) || '';
    for (const c of embedded || []) {
      if (!c || !c.name || seen.has(model + '\n' + c.name)) continue;
      seen.add(model + '\n' + c.name);
      out.push({ kind: '3d', name: c.name, duration: +c.duration || 0, file: model, drives: 'skeleton', source: 'embedded' });
    }
    return out;
  }

  // one tick of the play head: speed-scaled, wraps when looping, stops at the end otherwise
  function step(st, dt) {
    if (!st.playing) return st;
    const d = Math.max(0, st.duration || 0);
    let t = (st.t || 0) + Math.max(0, dt) * (st.speed || 1), playing = true;
    if (d <= 0) t = 0;
    else if (t >= d) { if (st.loop) t %= d; else { t = d; playing = false; } }
    return { ...st, t, playing };
  }

  // per control node [min, max] over a clip (tracks "mot_chNN.position", value in x) and the bar heights 0..1
  function ranges(clip) {
    const out = {};
    for (const tr of (clip && clip.tracks) || []) {
      const node = String(tr.name).split('.')[0], v = tr.values || [];
      let lo = Infinity, hi = -Infinity;
      for (let i = 0; i < v.length; i += 3) { if (v[i] < lo) lo = v[i]; if (v[i] > hi) hi = v[i]; }
      if (lo <= hi) out[node] = [lo, hi];
    }
    return out;
  }
  const bars = (values, rng) => values.map(([node, x]) => {
    const r = rng[node]; if (!r) return 0;
    return r[1] > r[0] ? Math.min(1, Math.max(0, (x - r[0]) / (r[1] - r[0]))) : 0.5;
  });

  // THREE.AnimationMixer over `root` (the model + any anims GLB scenes, model first so its bones bind by name)
  function player(THREE, root, onchange = () => {}) {
    const mixer = new THREE.AnimationMixer(root);
    let action = null, clip = null, controls = [], rng = {};
    const st = { name: '', t: 0, duration: 0, playing: false, loop: true, speed: 1 };
    const apply = () => { if (action) { action.time = st.t; mixer.update(0); } };
    const p = {
      state: st, mixer,
      load(c, drives = 'skeleton') {
        if (action) { action.stop(); mixer.uncacheAction(clip); }
        clip = c; action = mixer.clipAction(c); action.setLoop(THREE.LoopRepeat, Infinity); action.play();
        Object.assign(st, { name: c.name, t: 0, duration: c.duration || 0, playing: true });
        rng = drives === 'controls' ? ranges(c) : {};
        controls = Object.keys(rng).sort().map(n => [n, root.getObjectByName(n)]).filter(x => x[1]);
        apply(); onchange(st); return p;
      },
      play() { if (!clip) return p; if (!st.loop && st.t >= st.duration) st.t = 0; st.playing = true; onchange(st); return p; },
      pause() { st.playing = false; onchange(st); return p; },
      toggle() { return st.playing ? p.pause() : p.play(); },
      setLoop(on) { st.loop = !!on; onchange(st); return p; },
      setSpeed(x) { st.speed = SPEEDS.includes(+x) ? +x : 1; onchange(st); return p; },
      seek(t) { st.t = Math.min(Math.max(0, +t || 0), st.duration); apply(); onchange(st); return p; },
      stop() {                                   // stopping hands the bindings back: three restores each node's rest TRS
        if (action) { action.stop(); mixer.uncacheAction(clip); }
        action = clip = null; controls = []; rng = {};
        Object.assign(st, { name: '', t: 0, duration: 0, playing: false });
        onchange(st); return p;
      },
      update(dt) {
        if (!clip || !st.playing) return false;
        Object.assign(st, step(st, dt)); apply(); onchange(st); return true;
      },
      bars() { return bars(controls.map(([n, o]) => [n, o.position.x]), rng); },
      dispose() { p.stop(); mixer.stopAllAction(); mixer.uncacheRoot(root); },
    };
    return p;
  }

  const CSS = `.gbclips{margin-top:10px;border:1px solid var(--line,#333);border-radius:8px;padding:8px;font-size:12px}
.gbclips [hidden]{display:none!important}
.gbclips .gbc-h{display:flex;gap:8px;align-items:baseline}.gbclips .gbc-h b{flex:1}
.gbclips .gbc-q{width:100%;margin:6px 0;box-sizing:border-box}
.gbclips .gbc-list{max-height:180px;overflow:auto;display:grid;gap:2px}
.gbclips .gbc-row{display:flex;gap:6px;justify-content:space-between;text-align:left;padding:3px 6px;border-radius:4px;border:1px solid transparent;background:none;color:inherit;cursor:pointer;font:inherit}
.gbclips .gbc-row.on{border-color:var(--acc,#6cf);background:#6cf2}
.gbclips .gbc-row small{opacity:.65}
.gbclips .gbc-ctl{display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap}
.gbclips .gbc-ctl input[type=range]{flex:1;min-width:90px}
.gbclips .gbc-ctl button[aria-pressed=true]{border-color:var(--acc,#6cf)}
.gbclips .gbc-bars{width:100%;height:36px;display:block;margin-top:6px}
.gbclips .gbc-note{margin:6px 0 0;opacity:.75}`;

  function html(rows) {
    if (!rows.length) return '';
    const two = rows[0].kind === '2d';
    const items = rows.map((r, i) => `<button class="gbc-row" data-ci="${i}" title="${esc(r.source || r.name)}"><span>${esc(r.name)}</span>`
      + `<small>${r.duration ? fmt(r.duration) : r.frames ? r.frames + ' frames' : ''}${r.drives === 'controls' ? ' · controls' : ''}</small></button>`).join('');
    const ctl = two ? `<div class="gbc-ctl gbc-media" hidden><a class="act" data-c="mp4" target="_blank" rel="noopener" hidden>▶ MP4</a></div>`
      : `<div class="gbc-ctl" hidden><button class="act" data-c="play" title="Play / pause">▶</button>`
        + `<button class="act" data-c="loop" aria-pressed="true" title="Loop">⟲</button>`
        + `<select data-c="speed" title="Speed">${SPEEDS.map(s => `<option value="${s}"${s === 1 ? ' selected' : ''}>${s}×</option>`).join('')}</select>`
        + `<input type="range" data-c="scrub" min="0" max="1000" value="0" step="1" aria-label="Clip time"><output data-c="time">0.00 s</output>`
        + `<button class="act" data-c="stop" title="Stop: back to the rest pose">■</button></div><canvas class="gbc-bars" hidden></canvas>`;
    return `<div class="gbc-h"><b>Animations</b><span class="mut">${rows.length} clip${rows.length === 1 ? '' : 's'}</span></div>`
      + (rows.length > 12 ? `<input class="gbc-q" type="search" placeholder="Filter clips…" aria-label="Filter clips">` : '')
      + `<div class="gbc-list">${items}</div>${ctl}<p class="gbc-note mut" hidden></p>`;
  }

  // the clip panel inside `panel`; hooks: {load(row) -> Promise<{player, clip}> (3D), sprite(row) (2D), url(rel)}
  function mount(panel, rows, hooks) {
    if (!rows.length) { panel.hidden = true; return null; }
    if (typeof document !== 'undefined' && !document.getElementById('gbclips-css')) {
      const s = document.createElement('style'); s.id = 'gbclips-css'; s.textContent = CSS; document.head.append(s);
    }
    panel.hidden = false; panel.classList.add('gbclips'); panel.innerHTML = html(rows);
    const q = sel => panel.querySelector(sel), ui = { current: -1, player: null, pending: 0, scrubbing: false };
    const note = text => { const n = q('.gbc-note'); if (n) { n.textContent = text || ''; n.hidden = !text; } };
    ui.render = st => {
      const play = q('[data-c="play"]'); if (!play) return;
      play.textContent = st.playing ? '❚❚' : '▶';
      q('[data-c="loop"]').setAttribute('aria-pressed', String(st.loop));
      q('[data-c="speed"]').value = String(st.speed);
      if (!ui.scrubbing) q('[data-c="scrub"]').value = String(st.duration ? Math.round(1000 * st.t / st.duration) : 0);
      q('[data-c="time"]').textContent = `${fmt(st.t)} / ${fmt(st.duration)}`;
      const cv = q('.gbc-bars'), row = rows[ui.current];
      if (cv && row && row.drives === 'controls' && ui.player && cv.getContext) {
        const v = ui.player.bars(), g = cv.getContext('2d'), w = cv.width = cv.clientWidth || 300, h = cv.height = 36;
        g.clearRect(0, 0, w, h); g.fillStyle = '#6cf';
        v.forEach((x, i) => { const bw = w / v.length; g.fillRect(i * bw + 1, h - x * (h - 2) - 1, Math.max(1, bw - 2), x * (h - 2) + 1); });
      }
    };
    ui.select = async i => {
      const row = rows[i]; if (!row) return;
      ui.current = i;
      panel.querySelectorAll('.gbc-row').forEach(b => b.classList.toggle('on', +b.dataset.ci === i));
      if (row.kind === '2d') {
        const media = q('.gbc-media'), mp4 = q('[data-c="mp4"]');
        media.hidden = false; mp4.hidden = !row.mp4; if (row.mp4) mp4.href = hooks.url(row.mp4);
        hooks.sprite && hooks.sprite(row); note(row.frames ? `${row.frames} frames${row.fps ? ` at ${row.fps} fps` : ''}` : '');
        return;
      }
      const ticket = ++ui.pending;
      note('Loading clip…');
      try {
        const got = await hooks.load(row);
        if (ticket !== ui.pending) return;
        ui.player = got.player; got.player.load(got.clip, row.drives);
        q('.gbc-ctl').hidden = false; q('.gbc-bars').hidden = row.drives !== 'controls';
        note(row.drives === 'controls' ? 'Native control curves (IK parameters): the mesh does not move from them; the bars show their values.' : '');
      } catch (err) { if (ticket === ui.pending) note('Clip unavailable: ' + (err && err.message || err)); }
    };
    panel.onclick = e => {
      const row = e.target.closest('[data-ci]'); if (row) { ui.select(+row.dataset.ci); return; }
      const c = e.target.closest('[data-c]'), p = ui.player; if (!c || !p) return;
      if (c.dataset.c === 'play') p.toggle();
      else if (c.dataset.c === 'loop') p.setLoop(!p.state.loop);
      else if (c.dataset.c === 'stop') p.stop();
    };
    panel.oninput = e => {
      const c = e.target.closest('[data-c]');
      if (e.target.classList && e.target.classList.contains('gbc-q')) {
        const f = e.target.value.trim().toLowerCase();
        panel.querySelectorAll('.gbc-row').forEach(b => { b.hidden = !!f && !rows[+b.dataset.ci].name.toLowerCase().includes(f); });
        return;
      }
      const p = ui.player; if (!c || !p) return;
      if (c.dataset.c === 'scrub') { ui.scrubbing = true; p.pause(); p.seek(p.state.duration * (+c.value) / 1000); ui.scrubbing = false; }
      else if (c.dataset.c === 'speed') p.setSpeed(+c.value);
    };
    panel.onchange = panel.oninput;
    return ui;
  }

  window.GBoxClips = { list, step, fmt, ranges, bars, player, html, mount, SPEEDS, isSprite };
})();
