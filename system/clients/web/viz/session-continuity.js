/* A watched game survives session replacement. Never substitute an unrelated game. */
(function(root) {
  'use strict';
  const pc = s => String(s?.detail?.worker_name || s?.pc || '').toLowerCase();
  const build = s => String(s?.collection_mod || s?.mod_build || s?.mod || '').split('~')[0];
  const running = s => s?.state === 'running' && !s.stopping;
  function hasPicture(pixels) {
    let lit = 0;
    for (let i=0;i<pixels.length;i+=4) if (Math.max(pixels[i],pixels[i+1],pixels[i+2]) > 12) lit++;
    return lit >= Math.max(3, pixels.length/4*.005);
  }
  async function picture(url) {
    // Called in the same-origin game webview, also for the desktop shell.
    const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(4000)});
    if (!response.ok) throw Error('Waiting for game picture');
    const image = await createImageBitmap(await response.blob());
    try {
      const canvas = document.createElement('canvas');canvas.width=32;canvas.height=18;
      const context = canvas.getContext('2d',{willReadFrequently:true});context.drawImage(image,0,0,32,18);
      if (!hasPicture(context.getImageData(0,0,32,18).data)) return {visible:false};
      canvas.width=Math.min(image.width,960);canvas.height=Math.round(canvas.width*image.height/image.width);
      context.drawImage(image,0,0,canvas.width,canvas.height);
      return {visible:true,poster:canvas.toDataURL('image/jpeg',.85)};
    } finally {image.close();}
  }
  function resolve(id, rows, anchor = null) {
    const all = Array.isArray(rows) ? rows : [], byId = new Map(all.map(s => [s.session_id, s]));
    const origin = byId.get(id) || (anchor?.session_id === id ? anchor : null);
    if (!origin) return null;
    let current = origin; const seen = new Set();
    while (current?.replaced_by && !seen.has(current.session_id)) {
      seen.add(current.session_id);
      const next = byId.get(current.replaced_by);
      if (!next) break;
      current = next;
    }
    if (current !== origin && running(current)) return current;
    const stale = !running(origin) || origin.last_frame_age == null || origin.last_frame_age >= 15;
    if (stale && origin.game_id && pc(origin)) {
      const candidates = all.filter(s => running(s) && s.session_id !== id && s.game_id === origin.game_id &&
        pc(s) === pc(origin) && build(s) === build(origin) && s.started > (origin.started || 0) &&
        (!running(origin) || (s.last_frame_age != null && s.last_frame_age < 15)));
      candidates.sort((a,b) => b.started-a.started);
      if (candidates.length) return candidates[0];
    }
    return running(origin) ? origin : null;
  }
  function commandSession(id, rows, anchor = null) {
    const origin = (Array.isArray(rows) ? rows : []).find(s => s.session_id === id)
      || (anchor?.session_id === id ? anchor : null);
    const next = resolve(id, rows, origin);
    if (!next || !running(next) || next.worker_online === false) return null;
    // A replacement link may be stale/corrupt; a recovery command stays with the same known game.
    if (next.session_id !== id && (!origin?.game_id || next.game_id !== origin.game_id)) return null;
    return next;
  }
  function create(io) {
    let busy = false, anchor = null, generation = 0;
    const selected = () => { const value = io.current(); return typeof value === 'string' ? {session_id:value} : value; };
    async function poll() {
      const before = selected(); if (busy || !before?.session_id) return;
      const id = before.session_id, mine = generation;
      if (anchor?.session_id !== id) anchor = before;
      busy = true;
      try {
        const rows = await io.read(id);
        if (mine !== generation || selected()?.session_id !== id) return;
        anchor = rows.find(s => s.session_id === id) || anchor;
        const next = resolve(id, rows, anchor);
        if (next && next.session_id !== id) {
          await io.follow(next, id);
          if (selected()?.session_id === next.session_id) anchor = next;
        }
      } catch { /* API restarts retain the image and selected game; the next poll retries. */ }
      finally { busy = false; }
    }
    return {poll, cancel:() => {generation++; anchor=null;}};
  }
  const api = {resolve, commandSession, create, hasPicture, picture};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBoxSessionContinuity = api;
})(globalThis);
