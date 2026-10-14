// A frozen game frame, operator markings and optional character references.
(function (root) {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const MAX_BYTES = 4 * 1024 * 1024;
  function point(e, canvas) {
    const r = canvas.getBoundingClientRect();
    return { x: Math.max(0, Math.min(canvas.width, (e.clientX - r.left) * canvas.width / r.width)),
      y: Math.max(0, Math.min(canvas.height, (e.clientY - r.top) * canvas.height / r.height)) };
  }
  function mark(ctx, shape, number, scale) {
    const {a, b, tool} = shape;
    ctx.save(); ctx.strokeStyle = '#ff3535'; ctx.fillStyle = '#ff3535'; ctx.lineWidth = scale * 3;
    if (tool === 'box') ctx.strokeRect(Math.min(a.x,b.x), Math.min(a.y,b.y), Math.abs(b.x-a.x), Math.abs(b.y-a.y));
    else {
      const angle = Math.atan2(b.y-a.y,b.x-a.x), size = 14 * scale;
      ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(b.x,b.y);
      ctx.lineTo(b.x-size*Math.cos(angle-.45),b.y-size*Math.sin(angle-.45));
      ctx.lineTo(b.x-size*Math.cos(angle+.45),b.y-size*Math.sin(angle+.45)); ctx.closePath(); ctx.fill();
    }
    const x = Math.max(13*scale,Math.min(ctx.canvas.width-13*scale,a.x));
    const y = Math.max(13*scale,Math.min(ctx.canvas.height-13*scale,a.y));
    ctx.beginPath(); ctx.arc(x,y,12*scale,0,Math.PI*2); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.font = `bold ${14*scale}px sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(number),x,y); ctx.restore();
  }
  const css = `.bri-modal{position:fixed;inset:0;z-index:2147483100;background:#000c;display:grid;place-items:center;color:#eee;font:14px system-ui}
    .bri-box{box-sizing:border-box;background:#17181f;border:1px solid #555;border-radius:12px;padding:18px;width:min(1050px,96vw);max-height:96vh;overflow:auto}
    .bri-box h2{font-size:19px;margin:0 0 6px}.bri-sub{color:#b8bed0;margin:6px 0 12px;overflow-wrap:anywhere}
    .bri-tools,.bri-buttons{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
    .bri-box button{font:inherit;padding:7px 12px;color:#eee;background:#292c3a;border:1px solid #555;border-radius:5px;cursor:pointer}
    .bri-box button[aria-pressed=true],.bri-box button[data-send]{background:#5367c8}.bri-box button:disabled{opacity:.5;cursor:default}
    .bri-frame{text-align:center;background:#050506}.bri-frame canvas{display:block;max-width:100%;max-height:40vh;width:auto;height:auto;margin:auto;touch-action:none;cursor:crosshair}
    .bri-box textarea{box-sizing:border-box;width:100%;min-height:70px;margin-top:5px;background:#101116;color:#fff;border:1px solid #555;padding:8px;font:inherit}
    .bri-refs{display:flex;gap:10px;flex-wrap:wrap}.bri-refs figure{margin:5px 0;max-width:160px}.bri-refs img{max-width:150px;max-height:100px}.bri-refs figcaption{font-size:12px;overflow-wrap:anywhere}
    .bri-status{color:#c8cde0}.bri-buttons{position:sticky;bottom:-18px;background:#17181f;padding:10px 0;margin-bottom:0}.bri-box label{display:block;margin-top:12px}.bri-file{max-width:100%}`;
  function open(build, env = {}) {
    if (!build.session_id) return Promise.reject(new Error('This build is not the active game. Select its running session to capture a report.'));
    const doc = env.document || root.document, previous = doc.activeElement;
    const wrap = doc.createElement('div'); wrap.className = 'bri-modal';
    wrap.innerHTML = `<style>${css}</style><section class="bri-box" role="dialog" aria-modal="true" aria-label="Annotate build report" tabindex="-1">
      <h2>Show what is wrong with this build</h2><p class="bri-sub">${esc(build.game_title)} · ${esc(build.runtime_mod || build.name)}</p>
      <div class="bri-tools"><button type="button" data-tool="box" aria-pressed="true">Box</button><button type="button" data-tool="arrow" aria-pressed="false">Arrow</button><button type="button" data-undo>Undo</button><button type="button" data-clear>Clear marks</button><button type="button" data-retry hidden>Retry capture</button></div>
      <p class="bri-sub">Drag to mark a problem. Numbers match your note below. This is a still image; the game keeps running.</p>
      <div class="bri-frame"><canvas aria-label="Game screenshot: drag to draw boxes or arrows" hidden></canvas></div>
      <label>What still needs fixing?<textarea data-note maxlength="4000" data-nomic placeholder="For example: 1. Unnatural black spots on Mario's hat. 2. Missing shirt detail. The reference shows how he should look."></textarea></label>
      <label>Reference images (optional, up to 3)<input class="bri-file" data-files type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
      <p class="bri-sub">Choose, paste or drop a character image for comparison. The original frame, marked image and references go with your build report.</p>
      <div class="bri-refs"></div><div class="bri-buttons"><button type="button" data-send disabled>Submit report</button><button type="button" data-cancel>Cancel</button><span class="bri-status" role="status" aria-live="polite">Capturing game frame…</span></div></section>`;
    doc.body.appendChild(wrap);
    const q = s => wrap.querySelector(s), canvas = q('canvas'), ctx = canvas.getContext('2d');
    let original = '', frame = null, shapes = [], draft = null, tool = 'box', refs = [], busy = false, reading = false, closed = false;
    let resolve; const result = new Promise(r => { resolve = r; });
    const status = text => { q('[role=status]').textContent = text; };
    const available = () => { q('[data-send]').disabled = busy || reading || !frame; };
    const close = value => { if (closed) return; closed = true; doc.removeEventListener('keydown', key, true); wrap.remove(); previous?.focus?.(); resolve(value); };
    const key = e => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); if (!busy) close(null); }
      if (e.key === 'Tab') {
        const all = [...wrap.querySelectorAll('button:not(:disabled):not([hidden]), textarea, input')];
        const i = all.indexOf(doc.activeElement), next = (i + (e.shiftKey ? -1 : 1) + all.length) % all.length;
        e.preventDefault(); all[next]?.focus();
      }
    };
    doc.addEventListener('keydown', key, true); q('section').focus();
    function redraw() {
      if (!frame) return;
      ctx.drawImage(frame,0,0,canvas.width,canvas.height);
      [...shapes,...(draft ? [draft] : [])].forEach((s,i) => mark(ctx,s,i+1,Math.max(1,canvas.width/1000)));
    }
    async function capture() {
      q('[data-retry]').hidden = true; status('Capturing game frame…');
      try {
        const captured = await env.api(`/api/sessions/${encodeURIComponent(build.session_id)}/report-frame`, {}, 'POST');
        const image = new root.Image();
        await new Promise((yes,no) => { image.onload = yes; image.onerror = () => no(new Error('The game frame could not be displayed.')); image.src = 'data:image/png;base64,'+captured.image_b64; });
        if (closed) return;
        original = captured.image_b64; frame = image; canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        canvas.style.width = `min(100%, ${40 * canvas.width / canvas.height}vh)`;
        canvas.hidden = false; redraw(); available(); status('Ready to mark and report.');
      } catch (err) { if (!closed) { status('Capture failed: '+err.message); q('[data-retry]').hidden = false; } }
    }
    canvas.addEventListener('pointerdown', e => { if (!frame || busy || e.button !== 0) return; e.preventDefault();
      const a = point(e,canvas); draft = {tool,a,b:a}; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointermove', e => { if (draft) { draft.b = point(e,canvas); redraw(); } });
    canvas.addEventListener('pointerup', e => { if (!draft) return; draft.b = point(e,canvas);
      if (Math.hypot(draft.a.x-draft.b.x,draft.a.y-draft.b.y)>4) shapes.push(draft);
      draft = null; redraw(); });
    canvas.addEventListener('pointercancel', () => { draft = null; redraw(); });
    function renderRefs() {
      q('.bri-refs').innerHTML = refs.map((r,i) => `<figure><img alt="Reference ${i+1}" src="data:image/png;base64,${r.b64}"><figcaption>${esc(r.name)}</figcaption><button type="button" data-remove="${i}">Remove reference ${i+1}</button></figure>`).join('');
    }
    async function addFiles(files) {
      if (busy || reading) return; reading = true; available();
      try {
        for (const file of files) {
          if (refs.length >= 3) throw new Error('Up to 3 reference images. Remove one to add another.');
          if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > MAX_BYTES) throw new Error('Use PNG, JPEG or WebP images up to 4 MB each.');
          const url = root.URL.createObjectURL(file), img = new root.Image();
          try {
            await new Promise((yes,no) => { img.onload=yes; img.onerror=()=>no(new Error('Could not read reference image.')); img.src=url; });
            const out = doc.createElement('canvas'), ratio = Math.min(1,1600/Math.max(img.naturalWidth,img.naturalHeight));
            out.width=Math.max(1,Math.round(img.naturalWidth*ratio)); out.height=Math.max(1,Math.round(img.naturalHeight*ratio));
            out.getContext('2d').drawImage(img,0,0,out.width,out.height);
            const b64=out.toDataURL('image/png').split(',')[1];
            if (b64.length>Math.ceil(MAX_BYTES/3)*4) throw new Error('Reference image is too large after conversion. Use a smaller image.');
            if (closed) return;
            refs.push({name:file.name || 'character.png',b64}); renderRefs();
          } finally { root.URL.revokeObjectURL(url); }
        }
        status('Reference images added.');
      } catch (err) { status(err.message); }
      finally { reading=false; available(); q('[data-files]').value=''; }
    }
    q('[data-files]').addEventListener('change', e => addFiles([...e.target.files]));
    wrap.addEventListener('paste', e => { const files=[...(e.clipboardData?.files || [])]; if (files.length) { e.preventDefault(); addFiles(files); } });
    wrap.addEventListener('dragover', e => e.preventDefault());
    wrap.addEventListener('drop', e => { e.preventDefault(); addFiles([...(e.dataTransfer?.files || [])]); });
    wrap.addEventListener('click', async e => {
      const btn=e.target.closest('button'); if (!btn || busy) return;
      if (btn.hasAttribute('data-cancel')) return close(null);
      if (btn.dataset.tool) { tool=btn.dataset.tool; wrap.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b===btn))); }
      if (btn.hasAttribute('data-undo')) { shapes.pop(); redraw(); }
      if (btn.hasAttribute('data-clear')) { shapes=[]; draft=null; redraw(); }
      if (btn.hasAttribute('data-remove')) { refs.splice(+btn.dataset.remove,1); renderRefs(); }
      if (btn.hasAttribute('data-retry')) return capture();
      if (!btn.hasAttribute('data-send') || !frame || reading) return;
      busy=true; draft=null; redraw(); available(); status('Sending marked frame and references…');
      try {
        const c = root.GBoxBuildActions.reportCall(build,'broken',q('[data-note]').value);
        c.body.evidence={image_b64:canvas.toDataURL('image/png').split(',')[1],original_image_b64:original,reference_images:refs.map(r=>({...r}))};
        close(await env.api(c.path,c.body,'POST'));
      } catch (err) { busy=false; available(); status('Report failed: '+err.message+'. Your note and images are kept here; retry when ready.'); }
    });
    capture(); return result;
  }
  const api={open,point,mark};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.GBoxBuildReportImage=api;
})(typeof window!=='undefined' ? window : globalThis);
