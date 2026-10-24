/* [gbox-stream] GBOX GAMEPLAY ON THE LISTENER PAGE'S STAGE.
 *
 * The operator's switch is the master and this page never argues with it: the
 * station says show:false and the stage goes, whatever this page wanted. A
 * listener decides only what is on THEIR screen - the X hides the stage here
 * (remembered in this browser), the chip brings it back - and may tap a tile
 * in the strip to make it the big picture on this screen only.
 *
 * It rides the Pine Cam's own poll: /api/pinelink/mine carries a `gbox` block,
 * handed here by news() (the same hand-off PineStream gets). If that poll ever
 * stops arriving, a slow fallback asks /api/gbox/mine itself.
 *
 * Transport: the selected main view uses the same shared H.264/AAC HLS feed
 * on house, car and Funnel. Small thumbnails fetch one JPEG a second.
 * Gameplay has its own volume channel; sound requires a listener click.
 * A hidden tab stops all gameplay requests and resumes on return.
 *
 * While the mode is on and the operator keeps "station video as PiP", the
 * page's own gallery stage (#galleryStage - the artwork and the endless set)
 * gets the class gbox-pip and sits in the corner; its own show/tv classes are
 * untouched, so it still comes and goes with the station's video exactly as
 * before. Off, the class goes and it is back in place.
 */
(function () {
  "use strict";
  var HIDE_KEY = "pbfm.gbox.hidden";
  var CSS = "/gbox-tune/gbox-tune.css";
  var SNAP_MS = 1000;                 /* snapshots: the road's pace */
  var stage = null, head = null, what = null, main = null, mainImg = null, mainLabel = null, pill = null;
  var strip = null, veil = null, chip = null, mainVideo = null, player = null, playerLoad = null;
  var audioButton = null, gameplayLevel = null, audioStatus = null, playbackKey = "", gameplayVolume = 0.5;
  var on = false, hidden = false, state = "off", fps = 30, tiles = [], stationPip = true, why = "";
  var lastFlips = null, newsAt = 0, localMain = "", metadataDelayed = false;
  var views = {};                     /* key -> {img, tile, live, retryAt, pending, timer} */
  try { hidden = localStorage.getItem(HIDE_KEY) === "1"; } catch (e) { hidden = false; }
  try { var savedLevel = localStorage.getItem("pbfm.gbox.volume"); if (savedLevel !== null && Number.isFinite(Number(savedLevel))) gameplayVolume = Math.max(0, Math.min(1, Number(savedLevel))); } catch (e) {}

  function ensurePlayer() {
    if (player) return Promise.resolve(player);
    if (playerLoad) return playerLoad;
    playerLoad = new Promise(function (resolve, reject) {
      function ready() {
        if (!window.PineGBoxHls) { playerLoad = null; reject(new Error("Gameplay player unavailable")); return; }
        player = window.PineGBoxHls.create(mainVideo, {onStatus:function (s) {
          audioStatus.textContent = s.message;
          audioButton.textContent = s.enabled ? "Mute gameplay" : "Enable gameplay audio";
          audioButton.setAttribute("aria-pressed", s.enabled ? "true" : "false");
        }});
        player.volume(gameplayVolume);
        resolve(player);
      }
      if (window.PineGBoxHls) { ready(); return; }
      var script = document.createElement("script"); script.src = "/gbox-hls/pine-hls.js";
      script.onload = ready;
      script.onerror = function () { playerLoad = null; script.remove(); reject(new Error("Gameplay player unavailable")); };
      document.head.appendChild(script);
    });
    return playerLoad;
  }

  function onRoad() {
    var road = "house";
    try { road = currentRoad(); } catch (e) { road = "house"; }
    var car = false;
    try { car = (typeof streamMode !== "undefined") && !!streamMode; } catch (e) { car = false; }
    return car || road === "funnel";
  }
  function stamp(url) { return url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(); }
  function gallery() { return document.getElementById("galleryStage"); }
  function css() {
    if (document.querySelector('link[data-gbox-css]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = CSS; l.setAttribute("data-gbox-css", "1");
    document.head.appendChild(l);
  }

  function build() {
    if (stage) return;
    css();
    stage = document.createElement("div");
    stage.className = "gbox-stage";
    stage.setAttribute("role", "region");
    stage.setAttribute("aria-label", "gBox gameplay, live");
    head = document.createElement("div");
    head.className = "gbox-head";
    var dot = document.createElement("span"); dot.className = "gbox-dot";
    var name = document.createElement("b"); name.textContent = "gBox";
    what = document.createElement("span"); what.className = "gbox-what";
    head.appendChild(dot); head.appendChild(name); head.appendChild(what);
    main = document.createElement("div"); main.className = "gbox-main";
    mainImg = document.createElement("img"); mainImg.alt = "gBox gameplay";
    mainVideo = document.createElement("video"); mainVideo.className = "gbox-video";
    mainVideo.setAttribute("aria-label", "Live gameplay video"); mainVideo.hidden = true;
    mainLabel = document.createElement("div"); mainLabel.className = "gbox-label";
    pill = document.createElement("span"); pill.className = "gbox-pill"; pill.hidden = true;
    main.appendChild(mainImg); main.appendChild(mainVideo); main.appendChild(mainLabel); main.appendChild(pill);
    var audioRow = document.createElement("div"); audioRow.className = "gbox-audio";
    audioButton = document.createElement("button"); audioButton.type = "button";
    audioButton.textContent = "Enable gameplay audio"; audioButton.setAttribute("aria-pressed", "false");
    audioButton.addEventListener("click", function () { if (player) player.enableAudio(); });
    var levelLabel = document.createElement("label"); levelLabel.textContent = "Gameplay volume ";
    gameplayLevel = document.createElement("input"); gameplayLevel.type = "range";
    gameplayLevel.min = "0"; gameplayLevel.max = "1"; gameplayLevel.step = "0.01";
    gameplayLevel.value = String(gameplayVolume); gameplayLevel.setAttribute("aria-label", "Gameplay volume");
    gameplayLevel.addEventListener("input", function () {
      gameplayVolume = Number(gameplayLevel.value); if (player) player.volume(gameplayVolume);
      try { localStorage.setItem("pbfm.gbox.volume", String(gameplayVolume)); } catch (e) {}
    });
    levelLabel.appendChild(gameplayLevel);
    audioStatus = document.createElement("span"); audioStatus.setAttribute("role", "status");
    audioStatus.textContent = "Click Enable gameplay audio for game sound";
    audioRow.appendChild(audioButton); audioRow.appendChild(levelLabel); audioRow.appendChild(audioStatus);
    strip = document.createElement("div"); strip.className = "gbox-strip";
    veil = document.createElement("div"); veil.className = "gbox-veil"; veil.hidden = true;
    var x = document.createElement("button");
    x.type = "button"; x.className = "gbox-x"; x.title = "Hide the gameplay on this screen";
    x.setAttribute("aria-label", x.title); x.textContent = "×";
    x.addEventListener("click", function (ev) { ev.stopPropagation(); hide(); });
    stage.appendChild(head); stage.appendChild(main); stage.appendChild(audioRow); stage.appendChild(strip);
    stage.appendChild(veil); stage.appendChild(x);
    chip = document.createElement("button");
    chip.type = "button"; chip.className = "gbox-chip"; chip.title = "Show the gBox gameplay";
    chip.setAttribute("aria-label", chip.title); chip.textContent = "🎮 gBox gameplay";
    chip.addEventListener("click", function (ev) { ev.stopPropagation(); show(); });
    var g = gallery();
    if (g && g.parentNode) { g.parentNode.insertBefore(stage, g); g.parentNode.insertBefore(chip, g); }
    else { document.body.appendChild(stage); document.body.appendChild(chip); }
  }

  function vcr(want, burst) {
    if (want) build();
    if (!stage) return;
    var V = window.PineVcr;
    var o = {
      show: function () { stage.classList.add("show"); draw(); },
      hide: function () { if (!(on && !hidden)) stage.classList.remove("show"); }
    };
    if (!V) { if (want) o.show(); else stage.classList.remove("show"); return; }
    try { if (burst > 0) V.flip(stage, want, burst, o); else V.set(stage, want, o); }
    catch (e) { if (want) o.show(); else stage.classList.remove("show"); }
  }

  function tileLabel(t) {
    var where = t.device || "a PC";
    var title = t.title || "a game";
    var hint = (t.program ? " · gBox's pick" : "") + (/stills|crop/.test(String(t.picture || "")) ? " · " + esc(t.picture) : "");
    return "<b>" + esc(where) + "</b> · " + esc(title) + hint;
  }
  function esc(s) {
    return String(s || "").replace(/[&<>"]/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"}[c];
    });
  }

  function mainTile() {
    if (!tiles.length) return null;
    var pick = null;
    for (var i = 0; i < tiles.length; i++) if (tiles[i].key === localMain) pick = tiles[i];
    return pick || tiles[0];
  }

  function paint() {
    if (!stage) return;
    var m = mainTile();
    stage.classList.toggle("waiting", state !== "live");
    what.textContent = m ? ("· " + (m.device || "") + (tiles.length > 1 ? " +" + (tiles.length - 1) : "")) : "";
    var words = "";
    if (state === "waiting") words = "Waiting for gameplay on gBox" + (why ? " · " + why : "") + "…";
    veil.textContent = words;
    veil.hidden = !words;
    if (m) { mainLabel.innerHTML = tileLabel(m); mainLabel.hidden = false; }
    else { mainLabel.innerHTML = ""; mainLabel.hidden = true; }
    if (m && m.live === false) { pill.textContent = "holding the last picture…"; pill.hidden = false; }
    else if (m && typeof m.age === "number" && m.age > 8) { pill.textContent = "reconnecting…"; pill.hidden = false; }
    else pill.hidden = true;
    /* the strip: every tile but the main one, when there is more than one */
    var want = {};
    tiles.forEach(function (t) { want[t.key] = t; });
    Object.keys(views).forEach(function (k) {
      if (!want[k]) { stopView(k); if (views[k].tile && views[k].tile.parentNode) views[k].tile.parentNode.removeChild(views[k].tile); delete views[k]; }
    });
    tiles.forEach(function (t) {
      var v = views[t.key];
      if (!v) {
        v = views[t.key] = {img: null, tile: null, live: false, retryAt: 0, pending: false, url: ""};
        v.tile = document.createElement("div");
        v.tile.className = "gbox-tile";
        v.img = document.createElement("img");
        v.img.alt = "gBox gameplay on " + (t.device || "a PC");
        var lab = document.createElement("div"); lab.className = "gbox-label";
        v.tile.appendChild(v.img); v.tile.appendChild(lab);
        v.tile.addEventListener("click", (function (key) {
          return function () { localMain = key; stopView(key); paint(); draw(); };
        })(t.key));
      }
      v.tile.querySelector(".gbox-label").innerHTML = tileLabel(t);
      v.tile.classList.toggle("is-main", m && t.key === m.key);
      var inStrip = tiles.length > 1 && !(m && t.key === m.key);
      if (inStrip && v.tile.parentNode !== strip) strip.appendChild(v.tile);
      if (!inStrip && v.tile.parentNode === strip) strip.removeChild(v.tile);
    });
    if (chip) chip.classList.toggle("show", on && hidden);
    pip();
  }

  function pip() {
    var g = gallery();
    if (!g) return;
    g.classList.toggle("gbox-pip", on && !hidden && stationPip && state !== "off");
  }

  function hide() {
    hidden = true;
    stopAll();
    try { localStorage.setItem(HIDE_KEY, "1"); } catch (e) {}
    vcr(false, 0);
    paint();
  }
  function show() {
    hidden = false;
    try { localStorage.removeItem(HIDE_KEY); } catch (e) {}
    if (on) vcr(true, 0);
    paint();
    draw();
  }

  function stopView(key) {
    var v = views[key];
    if (!v) return;
    v.live = false; v.pending = false;
    if (v.img) { v.img.onload = null; v.img.onerror = null; v.img.removeAttribute("src"); }
    if (key === (mainTile() || {}).key && mainImg) { mainImg.onload = null; mainImg.onerror = null; mainImg.removeAttribute("src"); }
  }
  function stopAll() {
    playbackKey = "";
    if (player) player.stop();
    Object.keys(views).forEach(stopView);
    if (mainImg) { mainImg.onload = null; mainImg.onerror = null; mainImg.removeAttribute("src"); }
  }

  /* the picture of one tile into one <img>: the live stream in the house,
   * one JPEG a second on the road */
  function feed(t, img, v) {
    if (!img) return;
    var road = onRoad();
    if (!road && t.stream) {
      var url = t.stream + "&fps=" + Math.max(1, Math.min(30, fps || 12));
      if (v.live && v.url === url && img.getAttribute("src")) return;
      if (Date.now() < v.retryAt) return;
      v.live = true; v.url = url;
      img.onload = function () { if (state === "waiting") { state = "live"; paint(); } };
      img.onerror = function () { v.live = false; v.retryAt = Date.now() + 1500; img.removeAttribute("src"); };
      img.src = stamp(url);
      return;
    }
    if (v.pending || !t.frame) return;
    if (Date.now() < v.retryAt) return;
    v.pending = true; v.live = false;
    var pic = new Image();
    pic.onload = function () { v.pending = false; img.src = pic.src; v.retryAt = Date.now() + SNAP_MS; };
    pic.onerror = function () { v.pending = false; v.retryAt = Date.now() + Math.min(8000, SNAP_MS * 3); };
    pic.src = stamp(t.frame);
  }

  function draw() {
    if (!stage || !on || hidden || document.hidden || state === "off") { if (document.hidden) stopAll(); return; }
    var m = mainTile();
    if (m && m.hls) {
      if (playbackKey !== m.hls) {
        playbackKey = m.hls;
        mainVideo.hidden = false; mainImg.hidden = true;
        mainImg.onload = null; mainImg.onerror = null; mainImg.removeAttribute("src");
        var requested = playbackKey;
        ensurePlayer().then(function (p) {
          if (playbackKey === requested && on && !hidden && !document.hidden) p.source(requested);
        }).catch(function (e) { playbackKey = ""; audioStatus.textContent = String(e.message || e); });
      }
    } else {
      if (player && playbackKey) player.stop();
      playbackKey = ""; mainVideo.hidden = true; mainImg.hidden = false;
    }
    tiles.forEach(function (t) {
      var v = views[t.key];
      if (!v) return;
      if (m && t.key === m.key) {
        if (v.img && v.img.getAttribute("src") && v.tile.parentNode !== strip) v.img.removeAttribute("src");
        if (!t.hls) feed(t, mainImg, v);
      } else if (tiles.length > 1) {
        feed({frame:t.frame}, v.img, v);
      }
    });
  }
  function drawLoop() {
    try { draw(); } catch (e) {}
    setTimeout(drawLoop, 500);
  }

  /* one answer from the station: the gbox block of /api/pinelink/mine, or of
   * /api/gbox/mine when the fallback asked */
  function news(got) {
    newsAt = Date.now();
    if (!got || typeof got !== "object") return;
    metadataDelayed = false;
    var want = !!got.show;
    var nextState = String(got.state || (want ? "waiting" : "off"));
    fps = Number(got.fps) || 30;
    stationPip = got.station_pip !== false;
    why = String(got.why || "");
    var nextTiles = Array.isArray(got.tiles) ? got.tiles.filter(function (t) { return t && t.key; }) : [];
    var changed = JSON.stringify(nextTiles.map(function (t) { return [t.key, t.hls, t.stream, t.frame]; }))
      !== JSON.stringify(tiles.map(function (t) { return [t.key, t.hls, t.stream, t.frame]; }));
    // Feed identity belongs to draw(): title/thumbnail/list changes must not
    // destroy the healthy main decoder on every station metadata refresh.
    if (changed && localMain && !nextTiles.some(function (t) { return t.key === localMain; })) localMain = "";
    tiles = nextTiles;
    state = nextState;
    var sw = got.switch || null;
    var flips = sw ? Number(sw.flips || 0) : 0;
    var burst = (sw && sw.yours && lastFlips !== null && flips > lastFlips) ? flips - lastFlips : 0;
    if (sw) lastFlips = flips;
    if (want !== on || burst) {
      on = want;
      if (!hidden) vcr(on, burst);
      if (!on) { stopAll(); }
    }
    if (on) build();
    paint();
    draw();
  }
  async function fallback() {
    if (Date.now() - newsAt < 12000) return;
    try { news(await api("/api/gbox/mine")); }
    catch (e) {
      newsAt = Date.now(); metadataDelayed = true;
      // Only an explicit station show:false stops gameplay. A failed status
      // request is not evidence that an already-playing media feed ended.
    }
  }
  function fallbackLoop() {
    try { fallback(); } catch (e) {}
    setTimeout(fallbackLoop, document.hidden ? 30000 : 6000);
  }
  document.addEventListener("visibilitychange", function () { try { if (document.hidden) stopAll(); else draw(); } catch (e) {} });
  window.GBoxTune = {
    news: news, show: show, hide: hide,
    state: function () {
      return {on: on, hidden: hidden, picture: state, fps: fps, tiles: tiles.length, main: (mainTile() || {}).key || "",
              metadataDelayed: metadataDelayed,
              transport: (mainTile() || {}).hls ? "hls-h264-aac" : (onRoad() ? "snapshots" : "live"),
              gameplay: player ? player.state() : null, pip: !!(gallery() && gallery().classList.contains("gbox-pip"))};
    }
  };
  drawLoop();
  setTimeout(fallbackLoop, 15000);
})();
