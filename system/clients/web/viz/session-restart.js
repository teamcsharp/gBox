// Restart session / Reconnect stream (operator 2026-10-21: "The right click menu for a cloud session [should allow] an
// option to restart the session. Where it goes in and reinitializes and does whatever it takes to get the stream back up.")
//
// Restart = POST /api/sessions/{sid}/reset with mode "restart": the same game + mod relaunched on the same PC (the new copy
// starts beside the running one, which closes once the new one runs; Linux RPCS3 is closed first, the endpoint knows
// how). RPCS3 has no in-place reset, so this never uses session_op reset. Then the view follows the new session id, its
// streams are re-attached, and an autoplay that was playing the game is started again on the new copy.
// Reconnect = only the picture: every <img> streaming the session's MJPEG gets a fresh connection; the game is untouched.
//
// The server keeps its guards (reset_job): automated callers can't restart the operator's live game; this is an explicit
// operator click from the game's or the session icon's right-click menu. Shared by the web shell (clients/web/index.html)
// and the desktop app (clients/desktop/index.html: the PiP window's stream and the game menu).
(function (root) {
  'use strict';
  const MJPEG = /\/api\/sessions\/([^/?#]+)\/mjpeg(?:\?|$)/;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const JOB_LIMIT_MS = 16 * 60 * 1000;                     // the server waits up to 900 s for the relaunched game
  const KEEP_MODES = ['playbook', 'learned', 'vision'];     // a replay would reset the game again: those start as auto

  const sessionOf = src => decodeURIComponent((MJPEG.exec(String(src || '')) || [])[1] || '');
  function reconnectUrl(src, stamp) {                       // the same stream URL with a cache-busting reconnect mark
    const [path, query = ''] = String(src).split('?'), params = new URLSearchParams(query);
    params.set('reconnect', String(stamp));
    return path + '?' + params.toString();
  }
  // Fresh connections for every picture of these sessions in `doc`; returns how many were re-attached.
  function reconnectImages(doc, sids, stamp = Date.now()) {
    const want = new Set((Array.isArray(sids) ? sids : [sids]).filter(Boolean));
    let n = 0;
    for (const im of doc?.querySelectorAll ? doc.querySelectorAll('img') : []) {
      const src = im.getAttribute('src') || '';
      if (!want.has(sessionOf(src))) continue;
      im.setAttribute('src', reconnectUrl(src, stamp)); n++;
    }
    return n;
  }
  // the autoplay start for the new copy, from the old copy's status
  function autoplayInput(status) {
    return { op: 'start', mode: KEEP_MODES.includes(status?.mode) ? status.mode : 'auto' };
  }
  // the two menu entries (one wording for every menu that offers them)
  const ITEMS = [{ id: 'restart', icon: '↻', text: 'Restart session' }, { id: 'reconnect', icon: '⟳', text: 'Reconnect stream' }];
  const menuItems = () => ITEMS.map(x => ({ ...x }));
  const pcOf = sid => String(sid || '').split('-')[0] || 'its PC';
  function confirmText(s) {
    const who = s?.owner === 'agent' ? "the agent's test session " : '';
    return `Restart ${who}${s?.title || 'this game'} on ${s?.worker || pcOf(s?.session_id)}?\n\n` +
      'It is closed and started again from boot with the same mod; progress since your last save is lost. ' +
      'Use Reconnect stream instead if the game is fine and only the picture is stuck.';
  }

  // io: api(path, body) -> data (throws on HTTP errors), progress(pct, msg), show(title, sub, shot)?, fail(msg)?,
  //     follow(from, to) (the views move to the new copy), reconnect(sid) (re-attach its pictures),
  //     autoplay(sid, input) -> result (the session's autoplay job), delay(ms)?, now()?
  async function restart(io, { sid, title = '' } = {}) {
    if (!sid) throw new Error('No session to restart.');
    const delay = io.delay || wait, now = io.now || Date.now, say = (p, m) => io.progress && io.progress(p, m);
    const name = title || 'the game';
    io.show && io.show(`Restarting ${name}`, `Relaunching it on ${pcOf(sid)} with the same mod; the view follows the new copy`);
    say(2, 'Checking the autoplay');
    let auto = null;
    try { const st = io.autoplay ? await io.autoplay(sid, { op: 'status' }) : null; if (st && st.running) auto = st; } catch { /* no autoplay answer: none restarts */ }
    if (auto) {                                             // a frozen-game watcher must not race this relaunch
      say(4, 'Stopping the autoplay for the relaunch');
      try { await io.autoplay(sid, { op: 'stop' }); } catch { /* the old copy closes anyway */ }
    }
    let job;
    try {
      say(6, `Relaunching ${name} on ${pcOf(sid)}`);
      job = await io.api(`/api/sessions/${encodeURIComponent(sid)}/reset`, { mode: 'restart', intent: 'restart' });
      const until = now() + JOB_LIMIT_MS;
      while (job && /queued|running/.test(job.state)) {
        if (job.progress?.msg) say(Math.max(6, Math.min(90, job.progress.pct || 0)), job.progress.msg);
        if (now() > until) throw new Error('the relaunch did not finish in 16 minutes');
        await delay(500);
        job = await io.api('/api/jobs/' + encodeURIComponent(job.id));
      }
      if (!job || job.state !== 'succeeded') throw new Error((job && job.error) || `the relaunch ${job ? job.state : 'did not start'}`);
    } catch (err) {
      const msg = `Restart failed: ${err.message || err}`;
      if (auto) { try { await io.autoplay(sid, autoplayInput(auto)); } catch { /* the old copy may be gone */ } }
      io.fail && io.fail(msg);
      const error = new Error(msg); error.job = job?.id; throw error;
    }
    const out = job.output || {}, nsid = out.session_id || sid, notes = [...(out.notes || [])];
    say(92, 'Re-attaching the stream');
    try { if (io.follow) await io.follow(sid, nsid); } catch (e) { notes.push('The view did not follow by itself: ' + e.message); }
    try { if (io.reconnect) await io.reconnect(nsid); } catch (e) { notes.push('Stream: ' + e.message); }
    let autoplay = null;
    if (auto) {
      say(96, 'Starting the autoplay again');
      try {
        const r = await io.autoplay(nsid, autoplayInput(auto));
        autoplay = r && r.error ? { ok: false, error: r.error } : { ok: true, objective: r?.objective || r?.started || r?.already_running || '' };
      } catch (e) { autoplay = { ok: false, error: e.message }; }
      if (!autoplay.ok) notes.push(`The autoplay did not start again (${autoplay.error}); press F3 to start it.`);
    }
    say(100, nsid === sid ? 'Restarted' : `Restarted as ${nsid}`);
    return { ok: true, from: sid, session_id: nsid, job: job.id, autoplay, notes };
  }

  const api = { restart, reconnectImages, reconnectUrl, sessionOf, autoplayInput, menuItems, confirmText };
  root.GBoxSessionRestart = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
