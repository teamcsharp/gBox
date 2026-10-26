/* Pad takeover badge (gbox/pad_takeover.py; operator 2026-10-26: "pick up the controller and basically overwrite the
   gameplay by the bot for a brief moment in order to guide the agent ... and then just put down a controller and give
   the gameplay back to the bot ... on any system that's remoted in through G Box").
   The view forwards the operator's controller to the session it shows (index.html padTick; a game on this PC reads the
   controller itself and its worker watches the same pad). The worker running that session's bot lets go at the first
   press and takes the pad back takeover_idle_s after the last input with nothing held. This mirrors that rule for the
   badge, shown while the operator has the pad on a session whose bot runs:
       "You have control - put the pad down to give it back (3 s)"
   The seconds stay full while a button or the stick is held and count down once the pad is idle; the badge goes as the
   bot takes back over.
     GBoxPadTakeover.create({idleMs, now})   -> {observe(sid, keys), bot(sid, running, idleMs), known(sid, ms), state(),
                                                 reset()}: pure state, no timers (the page renders state() on its clock)
     GBoxPadTakeover.text(seconds)           -> the badge's words
     GBoxPadTakeover.countdown(msg, at, now) -> the desktop PiP's state from the view's {ev:"padtakeover"} message
     GBoxPadTakeover.mount(doc, {id})        -> {el, render(state)}: the badge, fixed at the top centre */
(function (root) {
  "use strict";
  const IDLE_MS = 3000;
  const WORDS = "You have control - put the pad down to give it back";
  const text = seconds => `${WORDS} (${seconds} s)`;
  const HIDDEN = Object.freeze({ show: false, sid: null, held: false, since: 0, last: 0, remainingMs: 0, idleMs: 0, seconds: 0,
                                 text: "" });

  function create({ idleMs = IDLE_MS, now = () => Date.now() } = {}) {
    let sid = null, prev = new Set(), streak = false, since = 0, last = 0, held = false;
    const bots = new Map();                                   // sid -> {running, idleMs, at}: the bot's live report
    const idleFor = s => { const b = bots.get(s); return b && b.idleMs > 0 ? b.idleMs : idleMs; };
    const expired = t => streak && !held && t - last >= idleFor(sid);
    const api = {
      // the session's bot as its report says (GET /api/autoplay/telemetry/{sid}: running, stats.operator_idle_s)
      bot(s, running, ms) {
        if (s) bots.set(s, { running: !!running, idleMs: Number(ms) > 0 ? Number(ms) : 0, at: now() });
      },
      known(s, maxAge = 6000) { const b = bots.get(s); return !!b && now() - b.at <= maxAge; },
      // what the operator's controller holds for session s right now (RetroPad keys); s null: no session shown
      observe(s, keys) {
        const t = now(), cur = new Set(keys || []);
        if ((s || null) !== sid) { sid = s || null; prev = new Set(); streak = false; held = false; }
        if (expired(t)) streak = false;                       // judged before this input: a key held until now kept it
        const pressed = [...cur].some(k => !prev.has(k)), changed = pressed || [...prev].some(k => !cur.has(k));
        prev = cur; held = cur.size > 0;
        if (!streak) {
          if (!pressed || !sid) return api.state();           // only a new press takes the pad (never a release)
          streak = true; since = t;
        }
        if (changed || held) last = t;
        return api.state();
      },
      state() {
        const t = now();
        if (expired(t)) streak = false;
        const bot = bots.get(sid);
        if (!streak || !bot || !bot.running) return { ...HIDDEN, sid };
        const total = idleFor(sid), remainingMs = held ? total : Math.max(0, total - (t - last));
        const seconds = Math.max(1, Math.ceil(remainingMs / 1000));
        return { show: true, sid, held, since, last, remainingMs, idleMs: total, seconds, text: text(seconds) };
      },
      reset() { sid = null; prev = new Set(); streak = false; held = false; }
    };
    return api;
  }

  // The desktop shell's PiP shows the view's badge (the view is hidden behind it): one message per change (every 5 s while
  // a key is held), the countdown runs on the shell's own clock from the moment the message came; a "held" the view
  // stopped repeating (HELD_STALE_MS) is over.
  const HELD_STALE_MS = 12000;
  function countdown(msg, at, now = Date.now()) {
    if (!msg || !msg.show || (msg.held && now - at > HELD_STALE_MS)) return { ...HIDDEN, sid: msg?.sid || null };
    const total = Number(msg.idle_ms) > 0 ? Number(msg.idle_ms) : IDLE_MS;
    const remainingMs = msg.held ? total : Math.max(0, (Number(msg.remaining_ms) || 0) - (now - at));
    if (!msg.held && remainingMs <= 0) return { ...HIDDEN, sid: msg.sid || null };
    const seconds = Math.max(1, Math.ceil(remainingMs / 1000));
    return { show: true, sid: msg.sid || null, held: !!msg.held, since: 0, last: at, remainingMs, idleMs: total, seconds,
             text: text(seconds) };
  }

  const CSS = `#ID{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2147483000;display:flex;align-items:center;
      gap:8px;max-width:calc(100vw - 32px);box-sizing:border-box;padding:6px 12px;border-radius:999px;background:#101318ee;color:#fff;
      border:1px solid #ff4fd8;box-shadow:0 2px 12px #0009;font:600 12px/1.3 system-ui,sans-serif;white-space:nowrap;cursor:default;
      -webkit-app-region:no-drag}
    #ID[hidden]{display:none!important}
    #ID .pt-dot{width:8px;height:8px;border-radius:50%;background:#ff4fd8;flex:none}
    #ID .pt-words{overflow:hidden;text-overflow:ellipsis}
    #ID .pt-secs{flex:none;font-variant-numeric:tabular-nums}
    #ID[data-held=false] .pt-dot{animation:pt-blink 1s steps(2,start) infinite}
    @keyframes pt-blink{50%{opacity:.25}}
    @media(prefers-reduced-motion:reduce){#ID .pt-dot{animation:none}}`;

  function mount(doc, { id = "pad-takeover" } = {}) {
    if (!doc || !doc.body) return { el: null, render() {} };
    let el = doc.getElementById(id);
    if (!el) {
      if (!doc.getElementById(id + "-css")) {
        const st = doc.createElement("style"); st.id = id + "-css"; st.textContent = CSS.split("#ID").join("#" + id);
        (doc.head || doc.body).append(st);
      }
      el = doc.createElement("div"); el.id = id; el.hidden = true;
      el.setAttribute("role", "status");
      el.innerHTML = `<span class="pt-dot" aria-hidden="true"></span><span class="pt-words">${WORDS}</span>` +
        `<span class="pt-secs" aria-hidden="true"></span>`;
      doc.body.append(el);
    }
    const secs = el.querySelector(".pt-secs");
    return {
      el,
      render(st) {
        const show = !!(st && st.show);
        if (el.hidden === show) el.hidden = !show;
        if (!show) return false;
        const s = `(${st.seconds} s)`;
        if (secs.textContent !== s) secs.textContent = s;
        el.dataset.held = String(!!st.held); el.dataset.sid = st.sid || "";
        el.title = st.text;
        return true;
      }
    };
  }

  const exported = { IDLE_MS, WORDS, text, create, countdown, mount };
  if (typeof module === "object" && module.exports) module.exports = exported; else root.GBoxPadTakeover = exported;
})(typeof window === "undefined" ? globalThis : window);
