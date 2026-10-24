/* Pine gameplay channel. Pinned Hls.js; native HLS on Safari.
 * One selected compressed video, bounded live buffer, actual AAC game audio.
 * No WebAudio mixer, microphone, station/DJ/SFX gain, or background encoder.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PineGBoxHls = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  var VERSION = '1.7.3', loading = null;
  function mediaUrl(value, page) {
    if (!value) return value;
    page = page || globalThis.location;
    try {
      var url = new URL(value, page.href);
      if (page.protocol === 'http:' && page.port === '8096' && url.origin === page.origin &&
          (url.pathname === '/api/gbox/hls' || url.pathname.indexOf('/gbox-hls/') === 0)) {
        url.port = '18098'; return url.href;
      }
    } catch (_) {}
    return value;
  }
  function loadHls() {
    if (globalThis.Hls && globalThis.Hls.version === VERSION) return Promise.resolve(globalThis.Hls);
    if (!loading) loading = new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = mediaUrl('/gbox-hls/hls-1.7.3.min.js');
      script.onload = function () {
        if (globalThis.Hls && globalThis.Hls.version === VERSION) resolve(globalThis.Hls);
        else { loading = null; reject(new Error('Gameplay player version mismatch')); }
      };
      script.onerror = function () { loading = null; script.remove(); reject(new Error('Gameplay player unavailable')); };
      document.head.appendChild(script);
    });
    return loading;
  }
  function canvasHold(video) {
    var doc = video.ownerDocument, parent = video.parentNode, canvas = null, valid = false;
    if (doc && parent && parent.appendChild) {
      canvas = doc.createElement('canvas'); canvas.className = 'gbox-hold'; canvas.hidden = true;
      canvas.setAttribute('aria-hidden', 'true');
      Object.assign(canvas.style, {position:'absolute', inset:'0', width:'100%', height:'100%',
        objectFit:'contain', pointerEvents:'none', background:'#000', zIndex:'1'});
      parent.appendChild(canvas);
    }
    return {
      capture:function () {
        if (!canvas || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
        try {
          var scale = Math.min(1, 960 / video.videoWidth, 540 / video.videoHeight);
          var w = Math.max(1, Math.round(video.videoWidth * scale)), h = Math.max(1, Math.round(video.videoHeight * scale));
          if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
          canvas.getContext('2d').drawImage(video, 0, 0, w, h); valid = true;
        } catch (_) { /* Retain the previously decoded picture if the new one is unavailable. */ }
      },
      show:function () { if (canvas && valid) canvas.hidden = false; },
      hide:function () { if (canvas) canvas.hidden = true; },
      reset:function () { valid = false; if (canvas) canvas.hidden = true; },
      held:function () { return !!(canvas && valid && !canvas.hidden); }
    };
  }
  function create(video, options) {
    options = options || {};
    var load = options.loadHls || loadHls, status = options.onStatus || function () {};
    var source = '', engine = null, generation = 0, timer = null, attempt = 0, audio = false, level = 0.5;
    var forceJs = false, transport = '', phase = 'stopped', errors = [], lastTime = -1, lastCapture = -Infinity;
    var lastMediaRecovery = -Infinity, hold = options.holdFrame || canvasHold(video), now = options.now || Date.now;
    var attachments = 0, stalls = 0, hasPlayed = false, stallActive = false;
    var waitingForBuffer = true, startBufferSeconds = 7.5;
    var schedule = options.setTimeout || setTimeout, cancel = options.clearTimeout || clearTimeout;
    video.autoplay = false; video.preload = 'auto'; video.playsInline = true; video.muted = true; video.volume = level;
    function report(message) { status({message:message, audio:audio && level > 0, enabled:audio, volume:level, source:source,
      phase:phase, transport:transport, holding:hold.held()}); }
    function audioMessage() { return audio ? (level ? 'Gameplay audio on' : 'Gameplay muted') : 'Click Enable gameplay audio for game sound'; }
    function bufferAhead() {
      var at = Number(video.currentTime) || 0;
      try { for (var i=0; i<video.buffered.length; i++) {
        var start=video.buffered.start(i), end=video.buffered.end(i);
        if(start<=at+.1 && end>at) return end-Math.max(start,at);
      } } catch (_) {}
      return 0;
    }
    function markStall() {
      if (hasPlayed && !stallActive) { stalls++; stallActive = true; }
    }
    function noteError(kind, details, fatal) {
      if (details === 'bufferStalledError') markStall();
      errors.push({at:now(), type:String(kind || 'unknown').slice(0,80), details:String(details || '').slice(0,160),
        fatal:!!fatal, transport:transport, time:Number(video.currentTime)||0});
      if (errors.length > 12) errors.shift();
    }
    function cleanup(preserve) {
      if (preserve) { hold.capture(); hold.show(); } else hold.reset();
      if (timer !== null) cancel(timer);
      timer = null;
      if (engine) engine.destroy();
      engine = null;
      video.onerror = null;
      video.pause(); video.removeAttribute('src'); video.load();
    }
    function play() {
      // Manifest length does not measure buffered media: the first appended
      // fragment exhausted the cushion during Pine's measured 4-8 s pauses.
      if (transport === 'hls.js' && !video.srcObject && waitingForBuffer && bufferAhead()<startBufferSeconds) {
        phase='buffering'; report('Buffering gameplay\u2026'); return;
      }
      waitingForBuffer=false;
      var epoch = generation;
      var task = video.play();
      if (task && task.catch) task.catch(function () {
        if (epoch !== generation) return;
        audio = false; video.muted = true; report('Click Enable gameplay audio to play with sound');
      });
    }
    function playing() {
      if (!source || video.error || video.readyState < 2 || video.paused===true) return;
      hasPlayed = true; stallActive = false;
      waitingForBuffer=false;
      if (timer !== null) cancel(timer);
      timer = null; attempt = 0; phase = 'playing'; hold.hide();
      if (now()-lastCapture >= 1000) { hold.capture(); lastCapture = now(); }
      report(audioMessage());
    }
    video.onplaying = playing;
    video.oncanplay = function () { if (source && !video.error) play(); };
    video.onwaiting = function () {
      if (!source) return;
      markStall();
      if(transport==='hls.js'&&!video.srcObject){waitingForBuffer=true;video.pause();}
      hold.capture(); hold.show(); phase = 'buffering'; report('Gameplay buffering…');
    };
    video.ontimeupdate = function () {
      var at = Number(video.currentTime);
      if (Number.isFinite(at) && at > lastTime + .02 && video.paused!==true) { lastTime = at; playing(); }
    };
    function retry(epoch, delay) {
      if (epoch !== generation || !source || timer !== null) return;
      hold.capture(); hold.show(); phase = 'recovering';
      report('Gameplay reconnecting…');
      timer = schedule(function () {
        timer = null;
        if (epoch === generation && source) attach(epoch, true);
      }, delay || Math.min(10000, 1000 * Math.pow(2, Math.min(attempt++, 4))));
    }
    async function attach(epoch, preserve) {
      cleanup(preserve);
      if (!source || epoch !== generation) return;
      attachments++;
      phase = preserve ? 'recovering' : 'loading'; lastTime = -1; waitingForBuffer=true;
      video.muted = !audio || level === 0;
      function nativeFallback() {
        if (forceJs || !video.canPlayType('application/vnd.apple.mpegurl')) return false;
        transport = 'native-hls';
        video.src = source; video.onerror = function () {
          noteError('native-media-error', video.error && video.error.message, true);
          // Some Chromium builds advertise native HLS then reject live MPEG-TS
          // at startup. Fall back to the pinned MSE player after a real error.
          forceJs = true; retry(epoch);
        }; play(); return true;
      }
      try {
        var Hls = await load();
        if (epoch !== generation || !source) return;
        // Native HLS in Chromium can advertise support but has an independent
        // live buffer and produced a real MPEG-TS demux failure in the probe.
        // Prefer the pinned MSE player so the configured live bounds apply.
        if (!Hls.isSupported()) {
          if (nativeFallback()) return;
          throw new Error('This browser cannot play H.264 gameplay');
        }
        transport = 'hls.js';
        // Wait for a real startup cushion instead of chasing a two-segment
        // cold playlist. Never seek the live playhead into an unbuffered hole.
        engine = new Hls({enableWorker:true, lowLatencyMode:false, initialLiveManifestSize:8,
          liveSyncMode:'buffered', liveSyncDurationCount:8,
          liveMaxLatencyDurationCount:24, maxLiveSyncPlaybackRate:1.03, backBufferLength:10,
          maxBufferLength:16, maxMaxBufferLength:24, maxBufferSize:16 * 1024 * 1024});
        var owned = engine;
        owned.on(Hls.Events.MANIFEST_PARSED, function () {
          if (epoch !== generation || owned !== engine) return;
          report(audioMessage()); play();
        });
        owned.on(Hls.Events.FRAG_BUFFERED, function () {
          if(epoch===generation && owned===engine && waitingForBuffer)play();
        });
        owned.on(Hls.Events.ERROR, function (_event, data) {
          if (epoch !== generation || owned !== engine) return;
          noteError(data.type, data.details, data.fatal);
          if (!data.fatal) return;
          if (Hls.ErrorTypes && data.type === Hls.ErrorTypes.MEDIA_ERROR && video.error &&
              typeof owned.recoverMediaError === 'function' && now()-lastMediaRecovery >= 5000) {
            lastMediaRecovery = now(); waitingForBuffer=true; hold.capture(); hold.show();
            try { owned.recoverMediaError(); retry(epoch, 5000); return; } catch (_) {}
          }
          retry(epoch);
        });
        owned.attachMedia(video); owned.loadSource(source);
      } catch (error) {
        if (epoch === generation && source) {
          noteError('player-load', error.message || error, true);
          if (!nativeFallback()) retry(epoch);
        }
      }
    }
    return {
      source:function (url) {
        url = mediaUrl(String(url || ''));
        if (url === source) return;
        source = url; generation++; attempt = 0; attachments = 0; stalls = 0;
        hasPlayed = false; stallActive = false;
        lastCapture = -Infinity; hold.reset();
        if (source) attach(generation); else { phase = 'stopped'; cleanup(); }
      },
      volume:function (value) {
        var next = Number(value);
        if (!Number.isFinite(next)) return;
        level = Math.max(0, Math.min(1, next)); video.volume = level; video.muted = !audio || level === 0;
        report(audioMessage());
      },
      enableAudio:function () {
        audio = !audio; video.muted = !audio || level === 0;
        report(audioMessage());
        if (source) play();
      },
      stop:function () { source = ''; generation++; phase = 'stopped'; cleanup(); },
      state:function () {
        return {source:source, audio:audio, volume:level, bufferedSeconds:24, bufferAheadSeconds:bufferAhead(),
          liveTargetSegments:8, startupBufferSeconds:startBufferSeconds, waitingForBuffer:waitingForBuffer,
          attachments:attachments, stalls:stalls,
          phase:phase, transport:transport, holding:hold.held(), errors:errors.slice()}; }
    };
  }
  return {VERSION:VERSION, create:create, loadHls:loadHls, mediaUrl:mediaUrl};
});
