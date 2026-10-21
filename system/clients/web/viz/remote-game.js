/* A game another PC plays natively, opened in the Sessions view (its header icon with the cloud, #2858: "when I click on
   a session ... show me in the window what is happening with the gameplay so I can watch the gameplay"). It used to show
   a card asking to pull the game here. Now the picture is that PC's live screen: its worker's desktop stream (GET
   /api/workers/{wid}/desktop/stream, the Other PC view's source) cropped to the game's own window while that screen shows
   it (view=game, workers with desktop_game_crop), else to its gBox window where the game is docked (view=app), else its
   whole desktop. A bar under the picture says which, offers the other two and Pull it to this PC.
   Watching only: nothing here sends input to the game. The picture changes in place (no re-render, no lost scroll). */
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const VIEWS = ["game", "app", "desktop"];
  const LABEL = { game: "Game", app: "gBox window", desktop: "Desktop" };
  const WHERE = { game: "game window", app: "gBox window", desktop: "whole desktop" };
  const RANK = { game: 0, app: 1, desktop: 2 };
  const FRESH_S = 10;             // a status whose newest frame is older says nothing about that screen now
  const QUIET_MS = 10000;         // no picture this long: say why, or try the next view down while that PC sends frames
  const pins = new Map();         // session id -> the view the operator picked (kept when the view is built again)
  let current = null;             // the Sessions view shows one game: one remote picture at a time

  const fresh = status => !!status && status.frames > 0 && status.last_frame_age != null && status.last_frame_age <= FRESH_S;
  const hasGame = (status, sid) => Array.isArray(status?.games) && status.games.includes(sid);
  // What that PC's screen can show of this game now (pure): the game's window, else gBox's, else the whole desktop;
  // skip: views that showed nothing here although frames came. null when the status has no fresh frame to judge by
  // (the stream is still starting): keep what is shown.
  function best(status, sid, skip = []) {
    if (!fresh(status)) return null;
    if (hasGame(status, sid) && !skip.includes("game")) return "game";
    return status.app_available && !skip.includes("app") ? "app" : "desktop";
  }
  // The automatic choice (pure). Before the first picture the best view is taken at once; after it a better view is
  // taken at once and a worse one only when two polls in a row agree, so a menu passing over the game on that PC does
  // not flip the picture. The operator's own pick always stays.
  function next(state, status, sid) {
    if (state.pinned) return { ...state, pending: null };
    const b = best(status, sid, state.skip);
    if (!b || b === state.view) return { ...state, pending: null };
    if (!state.shown || RANK[b] < RANK[state.view] || state.pending === b) return { ...state, view: b, pending: null };
    return { ...state, pending: b };
  }
  function streamUrl(wid, view, sid, auth) {
    const q = new URLSearchParams({ view });
    if (view === "game") q.set("session", sid);
    return `/api/workers/${encodeURIComponent(wid)}/desktop/stream?${q}${auth ? "&" + auth : ""}`;
  }
  // The bar's words for what is on screen (pure). A worker that reports its game windows also tells when the game is
  // not on its screen: the picture then is that screen without it.
  function describe(view, worker, status, { shown = false, errors = 0, sid = "" } = {}) {
    if (errors) return `Reconnecting to ${worker}'s screen…`;
    if (!shown) return `Connecting to ${worker}'s screen…`;
    const away = fresh(status) && Array.isArray(status.games) && !status.games.includes(sid) ? " · the game isn't on its screen right now" : "";
    const age = status?.last_frame_age;
    return `Live · ${worker} · ${WHERE[view]}${away}${age != null && age > FRESH_S ? ` · picture ${Math.round(age)} s old` : ""}`;
  }
  // What the picture area says until the first frame arrives (pure).
  function waiting(worker, status, waitedMs) {
    if (waitedMs >= QUIET_MS && !fresh(status))
      return `No picture from ${worker} yet: its gBox worker isn't sending its screen. The game keeps playing there.`;
    return `Connecting to ${worker}'s screen…`;
  }

  const CSS = `#remote-game { position:relative; overflow:hidden; }
    #remote-game img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
    #remote-game .rmg-wait { position:absolute; inset:0; display:grid; place-items:center; padding:20px; text-align:center; color:var(--mut); font-size:13px; }
    #remote-game .rmg-wait[hidden] { display:none; }
    #remote-game-bar { flex:none; display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:6px; padding:6px 8px;
      border:1px solid var(--line); border-radius:8px; background:var(--card); }
    #remote-game-meta { flex:1; min-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }
    #remote-game-meta i { display:inline-block; width:7px; height:7px; margin-right:6px; border-radius:50%; background:var(--ok,#3c3); vertical-align:1px; }
    #remote-game-meta.waiting i { background:var(--mut); }`;
  // The markup sessionsView puts where the game goes; the picture starts loading with the page (pure).
  // o: { sid, wid, worker, title, auth ("token=…"), crop (that worker crops to game windows), pull (offer Pull it here) }
  function html(o) {
    const view = pins.get(o.sid) || (o.crop ? "game" : "app");
    const why = `Running natively on ${o.worker}: the game plays on that PC's screen and this is a live picture of it. Inspect, memory edits and Blender copy still work from here.`;
    return `<style id="remote-game-css">${CSS}</style>
      <div id="remote-game" class="screen" data-session="${ESC(o.sid)}" data-worker-id="${ESC(o.wid)}" data-worker="${ESC(o.worker)}" data-crop="${o.crop ? 1 : 0}">
        <img id="remote-game-img" data-view="${view}" alt="${ESC(`Live picture of ${o.title || "the game"} on ${o.worker}`)}" draggable="false" src="${ESC(streamUrl(o.wid, view, o.sid, o.auth))}">
        <div id="remote-game-wait" class="rmg-wait" role="status">${ESC(`Connecting to ${o.worker}'s screen…`)}</div></div>
      <div id="remote-game-bar" role="toolbar" aria-label="${ESC(`Game on ${o.worker}`)}">
        <span id="remote-game-meta" class="mut waiting" title="${ESC(why)}"><i></i><span id="remote-game-what">${ESC(`Connecting to ${o.worker}'s screen…`)}</span></span>
        <span class="tabs2" role="group" aria-label="What to show">${VIEWS.map(v => `<button class="act${v === view ? " pri" : ""}" type="button" data-remote-view="${v}" aria-pressed="${v === view}"${v === "game" && !o.crop ? " disabled" : ""}
          title="${ESC(v === "game" ? (o.crop ? `Only the game's window, as ${o.worker}'s screen shows it` : `${o.worker}'s gBox worker can't crop to the game window yet (it needs a gBox update)`)
            : v === "app" ? `${o.worker}'s gBox window, where the game is docked` : `${o.worker}'s whole screen`)}">${LABEL[v]}</button>`).join("")}</span>
        <span id="remote-game-acts" hidden><button class="act" type="button" data-live-action="retry" title="Connect to ${ESC(o.worker)}'s screen again">Retry</button>
          <button class="act" type="button" data-live-action="stop" style="color:var(--bad)" title="Stop the game on ${ESC(o.worker)}">Stop</button>
          <button class="act" type="button" data-live-action="relaunch" title="Start this game again on ${ESC(o.worker)}: same game and build">Relaunch</button></span>
        ${o.pull ? `<button class="act pri" type="button" id="remote-game-pull" title="Save state there, start the same game (and mod) on this PC, load it, close the other copy">Pull it to this PC</button>` : ""}
      </div>`;
  }

  // Wires what html() made: status polls choose the view, errors reconnect, the bar's buttons. Returns { stop }.
  // o: { api(path) -> status JSON, auth() -> "token=…", pull(button), stop(button), relaunch(button), setTimer,
  // clearTimer, now }. Retry / Stop / Relaunch show in the bar while no picture comes: never an empty view without them.
  function mount(doc, o) {
    current?.stop();
    const box = doc.getElementById("remote-game");
    if (!box) return (current = null);
    const img = doc.getElementById("remote-game-img"), wait = doc.getElementById("remote-game-wait"),
          bar = doc.getElementById("remote-game-bar"), meta = doc.getElementById("remote-game-meta"),
          what = doc.getElementById("remote-game-what"), acts = doc.getElementById("remote-game-acts");
    const setTimer = o.setTimer || setTimeout, clearTimer = o.clearTimer || clearTimeout, now = o.now || Date.now;
    const sid = box.dataset.session, wid = box.dataset.workerId, worker = box.dataset.worker, crop = box.dataset.crop === "1";
    const opened = now();
    let st = { view: img.dataset.view, pinned: pins.has(sid), pending: null, shown: false, skip: [] };
    let status = null, timer = null, retry = null, stopped = false, errors = 0, trouble = false, since = opened;
    const live = () => !stopped && box.isConnected;

    function render() {
      if (!live()) return;
      st.shown = st.shown || img.naturalWidth > 0;
      meta.classList.toggle("waiting", !st.shown || errors > 0);
      what.textContent = describe(st.view, worker, status, { shown: st.shown, errors, sid });
      wait.hidden = st.shown;
      if (!st.shown) wait.textContent = errors ? describe(st.view, worker, status, { errors }) : waiting(worker, status, now() - opened);
      acts.hidden = !(errors > 0 || (!st.shown && now() - opened >= QUIET_MS));
      for (const b of bar.querySelectorAll("[data-remote-view]")) {
        const on = b.dataset.remoteView === st.view;
        b.classList.toggle("pri", on); b.setAttribute("aria-pressed", String(on));
        if (b.dataset.remoteView === "game") b.disabled = !(crop || hasGame(status, sid));
      }
    }
    function attach(view) {                      // a new stream only when the view changes or to recover one
      clearTimer(retry); retry = null; since = now();
      st.view = view; img.dataset.view = view;
      img.src = streamUrl(wid, view, sid, o.auth()) + "&t=" + now();
      render();
    }
    img.addEventListener("load", () => { errors = 0; render(); });
    img.addEventListener("error", () => {
      if (!live()) return;
      // an older server has no game view: take the gBox window instead of retrying it
      if (st.view === "game" && !st.pinned && !hasGame(status, sid)) return attach("app");
      errors++; render();
      clearTimer(retry);
      retry = setTimer(() => live() && attach(st.view), Math.min(10000, 1000 * 2 ** Math.min(errors, 4)));
    });
    bar.addEventListener("click", e => {
      const pick = e.target.closest("[data-remote-view]");
      if (pick && !pick.disabled) {
        pins.set(sid, pick.dataset.remoteView); st = { ...st, pinned: true, pending: null };
        if (pick.dataset.remoteView !== st.view) attach(pick.dataset.remoteView); else render();
        return;
      }
      const pull = e.target.closest("#remote-game-pull");
      if (pull && !pull.disabled) return o.pull(pull);
      const act = e.target.closest("[data-live-action]");
      if (!act || act.disabled) return;
      if (act.dataset.liveAction === "retry") { errors = 0; attach(st.view); clearTimer(timer); return poll(); }
      if (act.dataset.liveAction === "stop") return o.stop?.(act);
      if (act.dataset.liveAction === "relaunch") return o.relaunch?.(act);
    });
    box.addEventListener("contextmenu", e => e.stopPropagation());   // not the game picture's menu: this is a screen picture
    let polling = false;
    async function poll() {
      timer = null;
      if (!live()) return stop();
      if (polling) return;                       // Retry while a check is out: that one schedules the next
      polling = true;
      try {
        status = await o.api(`/api/workers/${encodeURIComponent(wid)}/desktop/status`);
        if (!live()) return;
        const was = st.view;
        st = next({ ...st, shown: st.shown || img.naturalWidth > 0 }, status, sid);
        // that PC sends frames but this view has shown nothing yet (a crop too small to make): the next view down
        if (st.view === was && !st.shown && !st.pinned && st.view !== "desktop" && fresh(status) && now() - since >= QUIET_MS)
          st = { ...st, skip: [...st.skip, st.view], view: st.view === "game" ? "app" : "desktop" };
        if (st.view !== was || trouble) attach(st.view); else render();   // the server is back: its old response may be gone
        trouble = false;
      } catch { trouble = true; if (live()) render(); }
      finally { polling = false; }
      if (live()) timer = setTimer(poll, st.shown ? 4000 : 1500);
    }
    function stop() { stopped = true; clearTimer(timer); clearTimer(retry); timer = retry = null; if (current === ctl) current = null; }
    const ctl = { stop, get view() { return st.view; } };
    current = ctl;
    render(); poll();
    return ctl;
  }

  root.GBoxRemoteGame = { best, next, streamUrl, describe, waiting, html, mount, pins };
  if (typeof module !== "undefined" && module.exports) module.exports = root.GBoxRemoteGame;
})(globalThis);
