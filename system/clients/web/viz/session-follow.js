/* The Sessions view always shows a game that is playing (operator 2026-10-20, about gBox left on "This session has
   ended" for an agent's RE4 session: "Every time I look over at gBox, the window looks like this. There's not even a
   game playing... That's the whole point of the screen saver is I need it playing games always").

   When the session the view shows has ended, or the view shows none, it moves to a running game: the broadcast
   program's (GET /api/broadcast: the operator's games first, else the newest game with a picture; bot and agent demos
   included), else the newest running session with a picture, else the newest running one. A line under the header
   says it moved ("Now showing DOA3 on i9-NUC: the RE4 session ended").
   It never leaves a running game. It stays on an ended session the operator pinned (the broadcast program pinned to
   it, or "Stay here"), and on the operator's own game that just ended for OWN_GRACE_S first, time to Reopen it.
   With nothing running, the ended view says when the autoplay screensaver starts a game, and why each PC doesn't yet
   (GET /api/autoplay-screensaver pcs). pick() / decide() / note() / waitHTML() / idleHTML() are pure; index.html wires
   them (followLive / followWatch). */
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const OWN_GRACE_S = 60;        // the operator's own game ended: this long to Reopen it before the view moves on
  const POLL_S = 10;             // an ended or empty view looks for a game this often
  const pcOf = s => s?.detail?.worker_name || s?.pc || String(s?.session_id || "").split("-")[0] || "another PC";
  const titleOf = s => s?.title || s?.game_title || "a game";
  const mins = s => s < 90 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`;

  // the running game to show instead of `except`: the broadcast program's, else the newest with a picture, else the
  // newest. judge(s, workers, now) (session-live.js) says whether a running game has a picture now.
  function pick(ss, program, { except = null, workers = null, now = Date.now() / 1000, judge = null } = {}) {
    const live = (Array.isArray(ss) ? ss : []).filter(s => s && s.state === "running" && !s.stopping && !s.warm && s.worker_online !== false && s.session_id !== except);   // not one on an offline PC (#2870)
    if (!live.length) return null;
    const prog = program && program.session_id && live.find(s => s.session_id === program.session_id);
    if (prog) return { session: prog, via: "broadcast" };
    const fresh = s => s.last_frame_age != null && s.last_frame_age < 15 ? 1 : 0;
    const pic = s => {                         // a picture now: a fresh frame, or a native game shown on its PC's screen
      if (!judge) return fresh(s);
      try {
        const v = judge(s, workers, now);
        return v.kind === "live" || v.kind === "screen" ? 1 : v.kind === "unknown" ? fresh(s) : 0;   // "starting": none yet
      } catch { return fresh(s); }
    };
    const best = live.slice().sort((a, b) => (pic(b) - pic(a)) || ((b.started || 0) - (a.started || 0)))[0];
    return { session: best, via: pic(best) ? "newest with a picture" : "newest" };
  }

  // leave `shown` (null: the view shows no session) for a running game now? -> { follow, why, wait_s? }
  function decide(shown, { program = null, pinned = null, now = Date.now() / 1000 } = {}) {
    if (!shown) return { follow: true, why: "nothing selected" };
    // a MercMode game parked / preloading in the background is paused: follow the one playing (operator 2026-10-24:
    // "why is the game always idle?" - the view stayed on parked RE4's death screen while RE5 played)
    if (shown.state === "running" && shown.warm) return { follow: true, why: "parked" };
    // a "running" game whose PC is offline (#2870, worker_online) is not playing: a demo's is left for a live game, the
    // operator's own stays with "Watch it now" offered; never a black view kept for hours (2026-10-26, i9-NUC Merc3D)
    const offline = shown.state === "running" && shown.worker_online === false;
    if (shown.state === "running" && !offline) return { follow: false, why: "playing" };
    if (pinned && pinned === shown.session_id) return { follow: false, why: "pinned" };
    if (program && program.mode === "session" && program.target === shown.session_id) return { follow: false, why: "pinned" };
    if (offline && !shown.agent_owned && !shown.bot_demo) return { follow: false, why: "offline" };
    if (!shown.agent_owned && !shown.bot_demo) {                       // the operator's own game: time to Reopen it
      const since = now - (shown.ended || now);
      if (since < OWN_GRACE_S) return { follow: false, why: "your game ended", wait_s: Math.ceil(OWN_GRACE_S - since) };
    }
    return { follow: true, why: offline ? "offline" : "ended" };
  }

  function note(from, to) {
    const now = `Now showing ${titleOf(to)} on ${pcOf(to)}`;
    if (!from) return `${now}: no game was selected`;
    if (from.state === "running" && from.worker_online === false) return `${now}: ${pcOf(from)} is offline`;
    return `${now}: the ${titleOf(from)} session ended`;
  }

  // the ended view while a game plays elsewhere but the view stays: the operator's own game (a countdown) or a pin
  function waitHTML(next, d) {
    const go = `<button class="act" data-follow-go="${ESC(next.session_id)}">Watch it now</button>`;
    const what = `<b>${ESC(titleOf(next))}</b> on ${ESC(pcOf(next))}`;
    if (d.why === "pinned") return `<p class="mut follow-wait" role="status">Pinned here. ${what} is playing. ${go}</p>`;
    if (d.why === "offline") return `<p class="mut follow-wait" role="status">This game's PC is offline. ${what} is playing. ${go}</p>`;
    return `<p class="mut follow-wait" role="status">Showing ${what} in ${ESC(mins(d.wait_s || 0))}. `
      + `<button class="act" data-follow-stay="1">Stay here</button> ${go}</p>`;
  }

  // the ended (or empty) view with nothing running: when the screensaver starts a game, and each PC's reason
  function idleHTML(st) {
    if (!st) return `<div class="follow-idle" role="status"><p><b>Nothing is playing.</b></p></div>`;
    const cfg = st.settings || {}, pcs = Array.isArray(st.pcs) ? st.pcs : [];
    let head;
    if (cfg.enabled === false) head = "Nothing is playing, and the autoplay screensaver is off";
    else {
      const can = pcs.filter(p => p.online && !p.reason);
      const idle = pcs.filter(p => p.online && p.starts_in_s > 0).sort((a, b) => a.starts_in_s - b.starts_in_s);
      head = can.length ? `Nothing is playing; the screensaver starts a game on ${can.map(p => p.name).join(" or ")} at its next check`
        : idle.length ? `Nothing is playing; the screensaver starts on ${idle[0].name} after ${cfg.idle_minutes || 10} min idle `
          + `(${mins(idle[0].starts_in_s)} to go)`
        : "Nothing is playing, and the screensaver can't start a game on any PC now";
    }
    const rows = pcs.map(p => `<li><b>${ESC(p.name)}</b>: ${ESC(p.reason || "can start a game now")}</li>`).join("");
    return `<div class="follow-idle" role="status"><p><b>${ESC(head)}</b></p>${rows ? `<ul class="mut">${rows}</ul>` : ""}</div>`;
  }

  root.GBoxSessionFollow = { pick, decide, note, waitHTML, idleHTML, OWN_GRACE_S, POLL_S };
  if (typeof module !== "undefined" && module.exports) module.exports = root.GBoxSessionFollow;
})(globalThis);
