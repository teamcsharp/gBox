/* Paint real model UVs. Changes stay in the preview until an explicit commit adapter accepts them. */
(function(root) {
  'use strict';
  const MiB = 1024 * 1024;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
  function canvas(width, height) {
    const result = document.createElement('canvas');
    result.width = width; result.height = height;
    return result;
  }
  function imageSize(image) {
    return [image.naturalWidth || image.videoWidth || image.width || 0, image.naturalHeight || image.videoHeight || image.height || 0];
  }
  async function decode(image) {
    if (typeof image !== 'string') return image;
    const result = new Image(); result.src = image;
    await result.decode(); return result;
  }
  function mount(host, options = {}) {
    const viewer = options.viewer;
    if (!viewer?.gltf?.scene || !viewer.THREE?.CanvasTexture || typeof viewer.paint !== 'function') {
      throw Error('Load an actual textured 3D model before opening mesh painting.');
    }
    const historyLimit = clamp(Number.isFinite(Number(options.historyBytes)) ? Number(options.historyBytes) : 64 * MiB, 0, 128 * MiB);
    const maxSize = clamp(Number(options.maxSize) || 4096, 1, 4096);
    const maxPixels = clamp(Number(options.maxPixels) || 16 * MiB, 1, 16 * MiB);
    let dead = false, selected = null, revision = 0, serial = 0, allocated = 0;
    let activeStroke = null, painting = false, committing = false, originalView = false;
    let undo = [], redo = [], historyBytes = 0;
    const rows = [], states = new Map(), materials = new Set();
    viewer.gltf.scene.traverse(object => {
      if (!object.isMesh) return;
      for (const material of [].concat(object.material || [])) {
        if (!material?.map?.image || materials.has(material)) continue;
        materials.add(material);
      }
    });
    const groups = options.materials || [...materials].map((material, i) => ({id: material.uuid || 'material-' + i, name: material.name || '', materials: [material]}));
    const assigned = new Set();
    for (const group of groups) {
      const bound = [...new Set(group.materials || [])].filter(material => materials.has(material) && !assigned.has(material));
      if (!bound.length) continue;
      for (const material of bound) assigned.add(material);
      const material = bound[0];
      rows.push({id: String(group.id ?? material.uuid ?? 'material-' + rows.length), name: group.name ?? material.name ?? '', image: group.image,
        material, originalMap: material.map, bindings: bound.map(material => ({material, originalMap: material.map}))});
    }
    host.innerHTML = `<section data-mtp class="model-texture-paint">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <label>Material <select data-mtp-material>${rows.map((row, i) => `<option value="${esc(row.id)}">${esc(row.name || 'Unnamed material ' + (i + 1))}</option>`).join('')}</select></label>
        <label><input type="checkbox" data-mtp-paint> Paint on model</label>
        <label>Tool <select data-mtp-tool><option value="color">Color</option><option value="erase">Erase to original</option><option value="hide">Mask: hide edit</option><option value="reveal">Mask: reveal edit</option></select></label>
        <label>Color <input type="color" data-mtp-color value="#f08060"></label>
        <label>Radius <input type="range" data-mtp-radius min="1" max="128" value="12"><output data-mtp-radius-label>12 px</output></label>
        <label>Opacity <input type="range" data-mtp-opacity min="1" max="100" value="100"></label>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0">
        <button type="button" data-mtp-undo disabled>Undo</button><button type="button" data-mtp-redo disabled>Redo</button>
        <label><input type="checkbox" data-mtp-wire checked> UV wire</label>
        <label><input type="checkbox" data-mtp-original> Show original</label>
        <label>2D view <select data-mtp-view><option value="result">Result</option><option value="mask">Mask</option><option value="edit">Editable texture</option></select></label>
        <button type="button" data-mtp-reset>Reset material</button>
        <button type="button" data-mtp-edit>Open in PhotoCraft</button>
        <button type="button" data-mtp-commit>Save texture edits</button>
      </div>
      <canvas data-mtp-canvas width="1" height="1" aria-label="Texture UV painting canvas" style="display:block;width:100%;max-height:48vh;object-fit:contain;image-rendering:pixelated;touch-action:none;background:repeating-conic-gradient(#333 0 25%,#484848 0 50%) 0/12px 12px"></canvas>
      <p role="status" aria-live="polite" data-mtp-status>Loading the model's original color map...</p>
    </section>`;
    const q = name => host.querySelector('[data-mtp-' + name + ']');
    const surface = q('canvas'), scratch = canvas(1, 1);
    const note = message => { if (!dead) q('status').textContent = message; };
    q('edit').hidden = typeof options.onEditImage !== 'function';
    q('commit').hidden = typeof options.onCommit !== 'function';
    function rowFor(value) {
      if (value === undefined || value === null) return selected;
      return rows.find(row => row.id === String(value)) || rows.find(row => row.name === value);
    }
    function buttons() {
      if (dead) return;
      q('undo').disabled = !undo.length || committing;
      q('redo').disabled = !redo.length || committing;
      q('commit').disabled = !states.size || committing;
      q('edit').disabled = !selected || committing;
    }
    function dataFor(state, kind) {
      return {id: state.row.id, material: state.row.name, image: state.row.image, width: state.width, height: state.height,
        png_data_url: state.result.toDataURL('image/png'), mask_data_url: state.mask.toDataURL('image/png'), kind, revision};
    }
    function changed(state, kind) {
      state.changed = true; revision++; buttons();
      try { options.onChange?.(dataFor(state, kind)); }
      catch (error) { note('Texture preview changed; the host could not receive it: ' + error.message); }
    }
    function composite(state) {
      const ctx = state.result.getContext('2d');
      ctx.globalCompositeOperation = 'source-over'; ctx.clearRect(0, 0, state.width, state.height); ctx.drawImage(state.original, 0, 0);
      ctx.globalCompositeOperation = 'destination-out'; ctx.drawImage(state.mask, 0, 0);
      scratch.width = state.width; scratch.height = state.height;
      const work = scratch.getContext('2d'); work.drawImage(state.edit, 0, 0);
      work.globalCompositeOperation = 'destination-in'; work.drawImage(state.mask, 0, 0);
      // Add premultiplied contributions instead of source-over: unchanged translucent texels retain their alpha.
      ctx.globalCompositeOperation = 'lighter'; ctx.drawImage(scratch, 0, 0); ctx.globalCompositeOperation = 'source-over';
      for (const binding of state.bindings) binding.texture.needsUpdate = true;
      if (selected === state.row) draw(state);
    }
    function draw(state) {
      surface.width = state.width; surface.height = state.height;
      // Keep the element's hit rectangle at the image aspect ratio, so pointer coordinates match pixels.
      surface.style.aspectRatio = state.width + '/' + state.height;
      surface.style.width = 'min(100%, ' + Math.max(256, state.width) + 'px)';
      surface.style.height = 'auto'; surface.style.maxHeight = 'none';
      const ctx = surface.getContext('2d');
      const image = originalView ? state.original : q('view').value === 'mask' ? state.mask : q('view').value === 'edit' ? state.edit : state.result;
      ctx.drawImage(image, 0, 0);
      if (q('wire').checked) {
        ctx.strokeStyle = '#65cfff'; ctx.lineWidth = Math.max(.4, state.width / 1024);
        const names = [...new Set(state.row.bindings.map(binding => binding.material.name))];
        for (const name of names) for (const line of viewer.uvLines?.(name, Math.floor(16000 / names.length)) || []) {
          if (rows.some(row => row !== state.row && row.bindings.some(binding => binding.material.name === name))) continue;
          ctx.beginPath();
          const map = state.row.bindings.find(binding => binding.material.name === name).originalMap;
          line.forEach(([u, v], i) => {
            if (viewer.THREE.Vector2 && map.transformUv) { const point = new viewer.THREE.Vector2(u, v); map.transformUv(point); u = point.x; v = point.y; }
            ctx[i ? 'lineTo' : 'moveTo'](u * state.width, v * state.height);
          });
          ctx.closePath(); ctx.stroke();
        }
      }
    }
    function ensure(row) {
      if (states.has(row.id)) return states.get(row.id);
      const [width, height] = imageSize(row.originalMap.image);
      if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) throw Error('This material has no readable color image.');
      if (width > maxSize || height > maxSize || allocated + width * height > maxPixels) throw Error('Texture preview memory limit reached. Close this editor before editing another large map.');
      const original = canvas(width, height), edit = canvas(width, height), mask = canvas(width, height), result = canvas(width, height);
      original.getContext('2d').drawImage(row.originalMap.image, 0, 0, width, height);
      // Fail before replacing a material if a cross-origin image cannot safely be exported.
      original.getContext('2d').getImageData(0, 0, 1, 1);
      edit.getContext('2d').drawImage(original, 0, 0);
      const maskCtx = mask.getContext('2d'); maskCtx.fillStyle = '#fff'; maskCtx.fillRect(0, 0, width, height);
      for (const binding of row.bindings) {
        if (imageSize(binding.originalMap.image).join(',') !== [width, height].join(',')) throw Error('A texture group must bind maps with the same native dimensions.');
      }
      const bindings = row.bindings.map(binding => {
        const texture = new viewer.THREE.CanvasTexture(result), source = binding.originalMap;
        for (const key of ['flipY', 'wrapS', 'wrapT', 'magFilter', 'minFilter', 'anisotropy', 'colorSpace', 'channel', 'generateMipmaps']) {
          if (source[key] !== undefined) texture[key] = source[key];
        }
        for (const key of ['repeat', 'offset', 'center']) if (texture[key]?.copy && source[key]) texture[key].copy(source[key]);
        texture.rotation = source.rotation || 0; texture.updateMatrix?.(); return {...binding, texture};
      });
      const state = {row, width, height, original, edit, mask, result, bindings, changed: false};
      allocated += width * height; states.set(row.id, state); composite(state);
      for (const binding of bindings) { binding.material.map = originalView ? binding.originalMap : binding.texture; binding.material.needsUpdate = true; }
      return state;
    }
    function snapshot(state) {
      return {id: state.row.id, width: state.width, height: state.height,
        edit: state.edit.getContext('2d').getImageData(0, 0, state.width, state.height),
        mask: state.mask.getContext('2d').getImageData(0, 0, state.width, state.height), bytes: state.width * state.height * 8};
    }
    function remember(state) {
      const bytes = state.width * state.height * 8;
      for (const item of redo) historyBytes -= item.bytes;
      redo = [];
      if (bytes > historyLimit) { note('This texture exceeds the undo memory budget. Export a copy before painting.'); return; }
      while (historyBytes + bytes > historyLimit && undo.length) historyBytes -= undo.shift().bytes;
      const entry = snapshot(state); undo.push(entry); historyBytes += entry.bytes; buttons();
    }
    function finishStroke() {
      if (!activeStroke) return;
      const stroke = activeStroke; activeStroke = null;
      if (stroke.changed && !dead) changed(stroke.state, 'stroke');
    }
    function announceSelection(state) {
      const turn = serial, row = state.row;
      Promise.resolve().then(() => { if (!dead && selected === row && serial === turn) return options.onSelect?.({id: row.id, material: row.name, image: row.image, width: state.width, height: state.height}); }).catch(error => note('Could not select the texture in the image editor: ' + error.message));
    }
    function usePaint() {
      painting = q('paint').checked && !originalView && !!selected;
      if (painting && !viewer.paintMaterialIds && rows.some(row => row !== selected && row.bindings.some(binding => selected.bindings.some(own => own.material.name === binding.material.name)))) {
        painting = false; q('paint').checked = false;
        note('These materials share a name. Use the UV canvas to edit this specific material.');
      }
      viewer.paint(painting ? hit => {
        const matches = selected?.bindings.some(binding => hit.materialId ? binding.material.uuid === hit.materialId : binding.material.name === hit.material);
        if (dead || committing || !matches || !Number.isFinite(hit.u) || !Number.isFinite(hit.v)) return;
        const event = hit.event || {};
        if (!activeStroke || event.type === 'pointerdown') {
          finishStroke(); beginStroke(ensure(selected), event.pointerId, 'model');
        }
        dab(hit.u, hit.v);
      } : null);
    }
    function beginStroke(state, pointerId, source) {
      remember(state); activeStroke = {state, pointerId, source, last: null, changed: false};
    }
    function dab(u, v) {
      if (!activeStroke || dead || committing || originalView || u < 0 || u > 1 || v < 0 || v > 1) return;
      const stroke = activeStroke, state = stroke.state, x = u * state.width, y = v * state.height;
      const radius = Number(q('radius').value), opacity = Number(q('opacity').value) / 100, tool = q('tool').value;
      const target = ['hide', 'reveal', 'erase'].includes(tool) ? state.mask : state.edit;
      const ctx = target.getContext('2d'); ctx.save(); ctx.globalAlpha = opacity;
      ctx.globalCompositeOperation = tool === 'hide' || tool === 'erase' ? 'destination-out' : 'source-over';
      ctx.fillStyle = tool === 'reveal' ? '#fff' : q('color').value;
      // Interpolate nearby samples only. UV islands and wrapping seams must never receive a connecting line.
      const last = stroke.last, distance = last ? Math.hypot(x - last[0], y - last[1]) : 0;
      const seamLimit = Math.max(radius * 3, Math.min(state.width, state.height) * .08);
      const steps = last && distance <= seamLimit ? Math.max(1, Math.ceil(distance / Math.max(1, radius / 3))) : 1;
      for (let i = 1; i <= steps; i++) {
        const px = steps > 1 ? last[0] + (x - last[0]) * i / steps : x, py = steps > 1 ? last[1] + (y - last[1]) * i / steps : y;
        ctx.beginPath(); ctx.arc(px, py, radius, 0, Math.PI * 2); ctx.fill();
        if (tool === 'color') {
          const mask = state.mask.getContext('2d'); mask.save(); mask.globalCompositeOperation = 'source-over'; mask.fillStyle = '#fff';
          mask.beginPath(); mask.arc(px, py, radius, 0, Math.PI * 2); mask.fill(); mask.restore();
        }
      }
      ctx.restore(); stroke.last = [x, y]; stroke.changed = true; composite(state);
    }
    function point(event) {
      const rect = surface.getBoundingClientRect();
      const scale = Math.min(rect.width / surface.width, rect.height / surface.height);
      const width = surface.width * scale, height = surface.height * scale;
      return [(event.clientX - rect.left - (rect.width - width) / 2) / width,
        (event.clientY - rect.top - (rect.height - height) / 2) / height];
    }
    surface.onpointerdown = event => {
      if (dead || committing || originalView || event.button !== 0 || !selected) return;
      finishStroke(); surface.setPointerCapture(event.pointerId); beginStroke(ensure(selected), event.pointerId, 'uv'); dab(...point(event)); event.preventDefault();
    };
    surface.onpointermove = event => {
      if (activeStroke?.source === 'uv' && activeStroke.pointerId === event.pointerId && event.buttons & 1) dab(...point(event));
    };
    const end = () => finishStroke();
    document.addEventListener('pointerup', end, true); document.addEventListener('pointercancel', end, true);
    surface.addEventListener('lostpointercapture', end);
    async function select(value) {
      if (dead) return false;
      finishStroke(); const row = rowFor(value); if (!row) throw Error('This model material is unavailable.');
      serial++; selected = row; q('material').value = row.id;
      try {
        const state = ensure(row); draw(state); usePaint(); buttons(); note((row.name || 'Unnamed material') + ' · ' + state.width + ' × ' + state.height + '. Preview only; original assets are unchanged.');
        announceSelection(state);
        return true;
      }
      catch (error) { selected = null; viewer.paint(null); surface.width = surface.height = 1; note(error.message); buttons(); return false; }
    }
    function history(direction) {
      finishStroke(); if (dead || committing) return false;
      const from = direction === 'undo' ? undo : redo, to = direction === 'undo' ? redo : undo;
      const entry = from.pop(); if (!entry) return false;
      historyBytes -= entry.bytes;
      const state = states.get(entry.id), next = snapshot(state); to.push(next); historyBytes += next.bytes;
      state.edit.getContext('2d').putImageData(entry.edit, 0, 0); state.mask.getContext('2d').putImageData(entry.mask, 0, 0);
      serial++; selected = state.row; q('material').value = state.row.id; composite(state); usePaint(); announceSelection(state); changed(state, direction); return true;
    }
    async function setImage(image, settings = {}) {
      if (dead) return false;
      const row = rowFor(settings.material); if (!row) throw Error('Select a material before loading an edited image.');
      const turn = ++serial, editTurn = revision, selection = selected, state = ensure(row), decoded = await decode(image);
      if (dead || turn !== serial || editTurn !== revision || selected !== selection) return false;
      const [width, height] = imageSize(decoded);
      if (width !== state.width || height !== state.height) throw Error('The edited image must keep the original texture size (' + state.width + ' × ' + state.height + ').');
      const imported = canvas(width, height); imported.getContext('2d').drawImage(decoded, 0, 0); imported.getContext('2d').getImageData(0, 0, 1, 1);
      finishStroke(); remember(state);
      const ctx = state.edit.getContext('2d'); ctx.clearRect(0, 0, width, height); ctx.drawImage(imported, 0, 0);
      const mask = state.mask.getContext('2d'); mask.clearRect(0, 0, width, height); mask.fillStyle = '#fff'; mask.fillRect(0, 0, width, height);
      composite(state); changed(state, 'image'); note('Edited image previewed on ' + (row.name || 'this material') + '. Save explicitly to retain it.'); return true;
    }
    function getImage(material) {
      if (dead) throw Error('Texture editor is closed.');
      const row = rowFor(material); if (!row) throw Error('Select a material first.');
      const state = ensure(row), result = canvas(state.width, state.height); result.getContext('2d').drawImage(state.result, 0, 0); return result;
    }
    function exportPNG(material) { return getImage(material).toDataURL('image/png'); }
    function exportEdits() {
      if (dead) throw Error('Texture editor is closed.');
      finishStroke(); return {version: 1, revision, textures: [...states.values()].filter(state => state.changed).map(state => dataFor(state, 'export'))};
    }
    async function commit() {
      if (dead || committing || typeof options.onCommit !== 'function') return false;
      finishStroke(); const payload = exportEdits(); if (!payload.textures.length) { note('No changed textures to save.'); return false; }
      committing = true; const turn = revision; buttons();
      try { const result = await options.onCommit(payload); if (!dead) note(turn === revision ? 'Texture edits saved by the mapping workflow.' : 'Saved earlier edits. Newer preview changes still need saving.'); return result ?? true; }
      catch (error) { if (!dead) note('Texture edits were not saved: ' + error.message); return false; }
      finally { committing = false; buttons(); }
    }
    q('material').onchange = () => select(q('material').value);
    q('paint').onchange = usePaint; q('wire').onchange = () => selected && draw(ensure(selected)); q('view').onchange = q('wire').onchange;
    q('radius').oninput = () => { q('radius-label').textContent = q('radius').value + ' px'; };
    q('original').onchange = () => {
      finishStroke(); originalView = q('original').checked;
      for (const state of states.values()) for (const binding of state.bindings) { binding.material.map = originalView ? binding.originalMap : binding.texture; binding.material.needsUpdate = true; }
      if (selected) draw(ensure(selected)); usePaint();
    };
    q('undo').onclick = () => history('undo'); q('redo').onclick = () => history('redo');
    q('reset').onclick = () => {
      if (dead || committing || !selected) return;
      finishStroke(); const state = ensure(selected); remember(state);
      const ctx = state.edit.getContext('2d'); ctx.clearRect(0, 0, state.width, state.height); ctx.drawImage(state.original, 0, 0);
      const mask = state.mask.getContext('2d'); mask.clearRect(0, 0, state.width, state.height); mask.fillStyle = '#fff'; mask.fillRect(0, 0, state.width, state.height);
      composite(state); changed(state, 'reset');
    };
    q('edit').onclick = async () => {
      if (dead || committing || !selected || typeof options.onEditImage !== 'function') return;
      finishStroke(); const row = selected, turn = serial, editTurn = revision, state = ensure(row);
      try {
        const result = await options.onEditImage({...dataFor(state, 'edit'), image: getImage(row.id)});
        if (result && !dead && selected === row && serial === turn && revision === editTurn) await setImage(result, {material: row.id});
      } catch (error) { if (!dead) note('Image editor could not return this texture: ' + error.message); }
    };
    q('commit').onclick = commit;
    const ready = (async () => {
      if (!rows.length) { note('This model has no paintable base-color texture. Load a textured model first.'); q('material').disabled = q('paint').disabled = true; buttons(); return false; }
      return select(options.material || rows[0].id);
    })();
    return {ready, select, setImage, getImage, exportPNG, exportEdits, commit,
      materials: () => rows.map(row => ({id: row.id, material: row.name, image: row.image})),
      selected: () => selected ? {id: selected.id, material: selected.name, image: selected.image} : null,
      dispose() {
        if (dead) return; finishStroke(); dead = true; serial++; viewer.paint(null);
        document.removeEventListener('pointerup', end, true); document.removeEventListener('pointercancel', end, true); surface.removeEventListener('lostpointercapture', end);
        for (const state of states.values()) {
          for (const binding of state.bindings) { binding.material.map = binding.originalMap; binding.material.needsUpdate = true; binding.texture.dispose(); }
          for (const layer of [state.original, state.edit, state.mask, state.result]) layer.width = layer.height = 1;
        }
        scratch.width = scratch.height = surface.width = surface.height = 1;
        states.clear(); undo = []; redo = []; historyBytes = allocated = 0; host.replaceChildren();
      }};
  }
  root.GBoxModelTexturePaint = {mount};
  if (typeof module === 'object' && module.exports) module.exports = {mount};
})(typeof window === 'undefined' ? globalThis : window);
