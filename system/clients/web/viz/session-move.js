// Move a running game between computers from its session chip's right-click menu (#1501): "Bring to this PC",
// "Load on the main computer" (the DGX Spark) or "Move to <PC>" for every other online worker. The move is the
// session_swap job (save the moment -> launch the same game + mod there -> load the moment -> close the old copy);
// while it runs the game's loading screen shows its last frame, the step and the progress.
(function (root) {
  const workerOf = (sid, workers) => {
    const prefix = String(sid || '').split('-')[0];
    return (workers || []).find(w => w.id === prefix) || null;
  };

  // Menu entries for a session: {to, label, hint, kind}. `local` is this PC's worker name ('' in a plain browser).
  function targets(sid, workers, local) {
    const here = workerOf(sid, workers), out = [];
    const online = (workers || []).filter(w => w.online && w.id !== here?.id && w.name !== here?.name);
    const mine = local ? online.find(w => w.name === local || w.id === local) : null;
    if (mine) out.push({ to: mine.name, kind: 'here', label: 'Bring to this PC', hint: `${mine.name} · native speed + your controller` });
    else if (!local && here?.os === 'linux') {                   // plain browser: the old Windows default stays reachable
      const win = online.find(w => w.os === 'windows');
      if (win) out.push({ to: win.name, kind: 'pc', label: `Move to ${win.name}`, hint: 'native speed + controls' });
    }
    const main = online.find(w => w.os === 'linux');
    if (main && !out.some(t => t.to === main.name))
      out.push({ to: main.name, kind: 'main', label: 'Load on the main computer', hint: `${main.name} · streamed here` });
    for (const w of online)
      if (!out.some(t => t.to === w.name)) out.push({ to: w.name, kind: 'pc', label: `Move to ${w.name}`, hint: w.os || '' });
    return out;
  }

  const wait = ms => new Promise(r => setTimeout(r, ms));

  // io: api(path, body), show(title, sub, shot), progress(pct, msg), fail(msg), done(newSid), frame(sid) -> url, delay(ms)
  async function run(io, { sid, to, title, label, mod = '' }) {
    const delay = io.delay || wait;
    io.show(`${title || 'Game'} → ${label || to}`, `Moving to ${to}: save the moment, start it there, load it, close this copy`,
            io.frame ? io.frame(sid) : '');
    io.progress(1, `Saving the moment on ${String(sid).split('-')[0]}`);
    let job;
    try {
      job = await io.api(`/api/sessions/${encodeURIComponent(sid)}/swap`, { mod, to, keep_state: true });
      while (/queued|running/.test(job.state)) {
        if (job.progress?.msg) io.progress(Math.max(1, Math.min(99, job.progress.pct || 0)), job.progress.msg);
        await delay(700);
        job = await io.api('/api/jobs/' + job.id);
      }
      if (job.state !== 'succeeded' || !job.output?.session_id) throw new Error(job.error || `the move ${job.state}`);
    } catch (err) {
      const msg = `Can't move it to ${to}: ${err.message || err}. The game keeps running where it was.`;
      io.fail(msg);
      return { ok: false, error: msg, job: job?.id };
    }
    io.progress(100, `Running on ${to} — opening it`);
    await io.done(job.output.session_id);
    return { ok: true, session_id: job.output.session_id, job: job.id };
  }

  const api = { targets, run, workerOf };
  root.GBoxSessionMove = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
