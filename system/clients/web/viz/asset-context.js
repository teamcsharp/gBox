// Shared image/asset context menu. Blender uses its native copybuffer, not a text URL.
(() => {
  const bound = new WeakMap();
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  function source(url, base) {
    const home = typeof base === 'function' ? base() : base || location.href;
    const parsed = new URL(url, home);
    if (parsed.origin !== new URL(home).origin) throw Error('Blender media must come from the gBox asset library.');
    return parsed.pathname; // the worker supplies its own auth; never enqueue a browser token
  }
  function bind(el, asset) { if (el) bound.set(el, asset); }
  function find(target) {
    for (let el = target; el; el = el.parentElement) {
      if (bound.has(el)) return { ...bound.get(el), image: target.closest?.('img') };
      if (el.dataset?.assetUrl) return { url: el.dataset.assetUrl, name: el.dataset.assetName,
        format: el.dataset.assetFormat, image: target.closest?.('img'),
        ...(el.dataset.assetCharacter ? {input:{character:el.dataset.assetCharacter}} : {}) };
    }
    const image = target.closest?.('img');
    return image ? { image, url: image.currentSrc || image.src, name: image.alt || 'Image', format: 'image' } : null;
  }
  async function png(image) {
    if (!image?.complete || !image.naturalWidth) throw Error('The image has not loaded yet.');
    if (image.naturalWidth * image.naturalHeight > 16000000) throw Error('Image exceeds the 16 megapixel clipboard limit.');
    const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    canvas.getContext('2d').drawImage(image, 0, 0); return canvas.toDataURL('image/png');
  }
  function mount(doc, io) {
    let menu = null;
    const close = () => { menu?.remove(); menu = null; };
    const handler = e => {
      if (e.defaultPrevented || e.target.closest?.('input,textarea,select,#scr,#nativeslot,.gbox-gpu-video,img.screen,img[src*="/mjpeg"],#pwcanvas')) return;
      const asset = find(e.target); if (!asset) return;
      e.preventDefault(); e.stopImmediatePropagation(); close();
      const isModel = !!asset.input?.character || /^(glb|gltf|uap)$/i.test(asset.format || '') || /\.(glb|gltf)(?:\?|$)/i.test(asset.url || '');
      const isImage = !isModel && (asset.image || /^(image|png|jpe?g|webp|apng|gif|bmp)$/i.test(asset.format || ''));
      menu = doc.createElement('div'); const panel = menu;
      panel.className = 'gbox-asset-menu'; panel.setAttribute('role', 'menu'); panel.setAttribute('aria-label', 'Copy asset');
      panel.style.cssText = 'position:fixed;z-index:2147483000;min-width:240px;max-width:340px;padding:8px;border:1px solid #555;border-radius:8px;background:#1c1e26;color:#fff;font:13px system-ui;box-shadow:0 8px 32px #0009';
      panel.innerHTML = `<b style="display:block;margin:2px 4px 8px;overflow-wrap:anywhere">${esc(asset.name || 'Asset')}</b>`
        + (asset.image ? '<button data-copy="image">Copy image to clipboard</button>' : '')
        + (isModel ? '<button data-copy="model">Copy model to Blender</button>' : '')
        + (isImage ? '<button data-copy="image_plane">Copy to Blender · Image plane</button><button data-copy="image_empty">Copy to Blender · Image empty</button>' : '')
        + (asset.mp4 || /^(mp4)$/i.test(asset.format || '') ? '<button data-copy="movie_plane">Copy to Blender · MP4 image plane</button>' : '')
        + (!isModel && !isImage && !asset.mp4 && !/^mp4$/i.test(asset.format || '') ? '<button data-copy="asset">Copy asset</button>' : '')
        + '<div role="status" style="margin:6px 4px;max-width:300px;overflow-wrap:anywhere">In Blender, hover a 3D viewport and press Ctrl+V.</div>';
      for (const b of panel.querySelectorAll('button')) { b.type = 'button'; b.style.cssText = 'display:block;width:100%;text-align:left;border:0;border-radius:4px;background:#303440;color:white;padding:8px;margin:3px 0;cursor:pointer;font:inherit'; }
      (e.target.closest?.('dialog[open]') || doc.body).append(panel); io.place?.(panel, e.clientX, e.clientY);
      if (!io.place) { panel.style.left = Math.max(4, Math.min(e.clientX, innerWidth - panel.offsetWidth - 4)) + 'px'; panel.style.top = Math.max(4, Math.min(e.clientY, innerHeight - panel.offsetHeight - 4)) + 'px'; }
      panel.onclick = async ev => {
        const button = ev.target.closest('[data-copy]'); if (!button || button.disabled) return;
        const mode = button.dataset.copy, status = panel.querySelector('[role=status]');
        panel.querySelectorAll('button').forEach(b => b.disabled = true); status.textContent = 'Copying…';
        try {
          if (mode === 'image') { await io.image(await png(asset.image)); status.textContent = 'Image copied to clipboard.'; }
          else if (mode === 'asset') { await io.asset(asset); status.textContent = 'Copied to the gBox asset clipboard.'; }
          else {
            let input;
            if (mode === 'model') input = asset.input || { asset_url: source(asset.url, io.sourceBase) };
            else if (mode === 'movie_plane') input = { asset_url: source(asset.mp4 || asset.url, io.sourceBase), paste_as: mode };
            else if (asset.image) input = { image_b64: (await png(asset.image)).split(',')[1], paste_as: mode };
            else input = { asset_url: source(asset.url, io.sourceBase), paste_as: mode };
            const result = await io.blender(input);
            status.textContent = `Copied ${mode.replaceAll('_', ' ')}${result.host ? ' on ' + result.host : ''}. In Blender, hover a 3D viewport and press Ctrl+V.`
              + (mode === 'movie_plane' ? ' Play the timeline to animate. MP4 has an opaque background; its file stays on this PC.' : '');
          }
        } catch (err) { status.textContent = 'Copy failed: ' + err.message; }
        finally { panel.querySelectorAll('button').forEach(b => b.disabled = false); }
      };
    };
    doc.addEventListener('contextmenu', handler, true);
    const outside = e => { if (menu && !menu.contains(e.target)) close(); };
    const key = e => { if (e.key === 'Escape') close(); };
    doc.addEventListener('pointerdown', outside, true); doc.addEventListener('keydown', key);
    window.addEventListener('blur', close);
    return { close, dispose() { close(); doc.removeEventListener('contextmenu', handler, true); doc.removeEventListener('pointerdown', outside, true); doc.removeEventListener('keydown', key); window.removeEventListener('blur', close); } };
  }
  window.GBoxAssetContext = { bind, find, png, mount };
})();
