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
      var settled = false;
      function failed(message) {
        if (settled) return;
        settled = true; clearTimeout(guard); loading = null; script.remove(); reject(new Error(message));
      }
      var guard = setTimeout(function () { failed('Gameplay player load timed out'); }, 15000);
      script.onload = function () {
        if (settled) return;
        if (globalThis.Hls && globalThis.Hls.version === VERSION) {
          settled = true; clearTimeout(guard); resolve(globalThis.Hls);
        } else failed('Gameplay player version mismatch');
      };
      script.onerror = function () { failed('Gameplay player unavailable'); };
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
    var attachment = 0, autoplayBlocked = false;
    var forceJs = false, transport = '', phase = 'stopped', errors = [], lastTime = -1, lastCapture = -Infinity;
    var lastMediaRecovery = -Infinity, hold = options.holdFrame || canvasHold(video), now = options.now || Date.now;
    var attachments = 0, stalls = 0, hasPlayed = false, stallActive = false, catchups = 0;
    var waitingForBuffer = true, startBufferSeconds = 7.5;
    // [smooth] 2026-11-10: seams stepped over and stalls re-synced (see play()).
    var seams = 0, resyncs = 0, resyncedThisStall = false, SEAM_S = 0.6;
    var schedule = options.setTimeout || setTimeout, cancel = options.clearTimeout || clearTimeout;
    var watch = null, watchTime = -1, watchFrames = null, advancedAt = now();
    var every = options.setInterval || setInterval, unevery = options.clearInterval || clearInterval;
    function watchProgress() {
      if (!source || autoplayBlocked) return;
      if (video.ownerDocument && video.ownerDocument.hidden) { advancedAt=now(); return; }
      var at=Number(video.currentTime)||0;
      var frames=null;
      try { var q=video.getVideoPlaybackQuality&&video.getVideoPlaybackQuality();if(q&&Number.isFinite(q.totalVideoFrames))frames=q.totalVideoFrames; }catch(_){}
      // A browser may expose the quality API but leave its counters at zero.
      // Once it reports frames, use those to catch a frozen picture even when
      // the audio clock continues; a reset counter starts a fresh observation.
      var advanced=frames>0 ? watchFrames===null||frames!==watchFrames : at>watchTime+.02;
      watchTime=at;watchFrames=frames;
      // A progressing decoder can still be far behind after a background tab
      // or a long network stall. Catch up only inside buffered media and keep
      // the proven startup cushion. Audio and video seek together in one player.
      if (hasPlayed && !video.paused && video.readyState >= 3 && !video.seeking) {
        try {
          const ranges=video.buffered;
          if(ranges.length){
            const i=ranges.length-1, end=ranges.end(i), start=ranges.start(i);
            if(end-at>16 && end-start>=startBufferSeconds+1){
              video.currentTime=Math.max(start,end-startBufferSeconds-1);
              catchups++;advancedAt=now();return;
            }
          }
        } catch (_) {}
      }
      if(advanced){advancedAt=now();return;}
      if (now()-advancedAt < (hasPlayed ? 15000 : 30000) || timer!==null) return;
      advancedAt=now(); noteError('watchdog','playhead stopped progressing',false); retry(generation,250);
    }
    function startWatch() { if(watch!==null)return;watch=every(watchProgress,2000);if(watch&&watch.unref)watch.unref(); }
    function stopWatch() { if(watch!==null)unevery(watch);watch=null; }
    video.autoplay = false; video.preload = 'auto'; video.playsInline = true; video.muted = true; video.volume = level;
    function report(message) { status({message:message, audio:audio && level > 0, enabled:audio, volume:level, source:source,
      phase:phase, transport:transport, holding:hold.held()}); }
    function audioMessage() { return audio ? (level ? 'Gameplay audio on' : 'Gameplay muted') : 'Click Enable gameplay audio for game sound'; }
    function bufferAhead(position) {
      // [smooth] Contiguous media ahead, ACROSS small seams between segments.
      // The old reading stopped at the first seam: a stall parked on one
      // read 0 s forever (the video is paused, so hls.js's own gap nudging
      // is off), and only the 15 s watchdog's full rebuild got it out.
      var at = position === undefined ? Number(video.currentTime) || 0 : position, reach = at, found = false;
      try { for (var i=0; i<video.buffered.length; i++) {
        var start=video.buffered.start(i), end=video.buffered.end(i);
        if (end <= reach) continue;
        if (start > reach + SEAM_S) break;
        reach = end; found = true;
      } } catch (_) {}
      return found ? reach - at : 0;
    }
    function skipSeam() {
      // [smooth] Standing in a seam with media just ahead: step onto it.
      var at = Number(video.currentTime) || 0;
      try { for (var i=0; i<video.buffered.length; i++) {
        var start=video.buffered.start(i), end=video.buffered.end(i);
        if (start <= at && end > at) return false;
        if (start > at && start - at <= SEAM_S && end > start) {
          video.currentTime = start + Math.min(0.01, (end-start)/2); seams++; return true;
        }
      } } catch (_) {}
      return false;
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
      // [smooth] 2026-11-10 (operator: "the delay isn't bad, I just don't want
      // stutters"): a stall has already frozen the picture, so THAT is when to
      // drop the time it cost - once, back to the live target - instead of
      // playing faster for minutes afterwards (uneven frame steps) or jumping
      // later at the edge of gBox's 12-segment window.
      if (transport === 'hls.js' && waitingForBuffer && hasPlayed && !resyncedThisStall && engine) {
        var target = Number(engine.liveSyncPosition), at = Number(video.currentTime) || 0;
        if (Number.isFinite(target) && target - at > 2 && bufferAhead(target) >= startBufferSeconds) {
          // A manifest target can be ahead of fetched media. Seek only into
          // an actual buffered range, retaining the startup cushion there.
          try { for (var i=0; i<video.buffered.length; i++) {
            if (video.buffered.start(i) <= target && video.buffered.end(i) > target) {
              video.currentTime = target; resyncedThisStall = true; resyncs++; break;
            }
          } } catch (_) {}
        }
      }
      if (transport === 'hls.js' && !video.srcObject && waitingForBuffer && bufferAhead()<startBufferSeconds) {
        phase='buffering'; report('Buffering gameplay\u2026'); return;
      }
      if (transport === 'hls.js' && waitingForBuffer) skipSeam();
      waitingForBuffer=false;
      var epoch = generation, ownAttachment = attachment;
      var task = video.play();
      if (task && task.catch) task.catch(function (error) {
        if (epoch !== generation || ownAttachment !== attachment) return;
        if (error && error.name === 'NotAllowedError') autoplayBlocked = true;
        audio = false; video.muted = true; report('Click Enable gameplay audio to play with sound');
      });
    }
    function playing() {
      if (!source || video.error || video.readyState < 2 || video.paused===true) return;
      hasPlayed = true; stallActive = false; resyncedThisStall = false;
      autoplayBlocked = false;
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
      var ownAttachment = ++attachment;
      attachments++;watchTime=-1;watchFrames=null;advancedAt=now();
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
        if (epoch !== generation || ownAttachment !== attachment || !source) return;
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
          // [smooth] no playback-rate nudging: 1.03x turns 30 fps into uneven
          // frame steps on a 60 Hz screen. Drift is dropped during stalls instead.
          liveMaxLatencyDurationCount:24, maxLiveSyncPlaybackRate:1, backBufferLength:10,
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
        if (epoch === generation && ownAttachment === attachment && source) {
          noteError('player-load', error.message || error, true);
          if (!nativeFallback()) retry(epoch);
        }
      }
    }
    return {
      source:function (url) {
        url = mediaUrl(String(url || ''));
        if (url === source) return;
        source = url; generation++; attempt = 0; attachments = 0; stalls = 0; catchups = 0;
        hasPlayed = false; stallActive = false; autoplayBlocked = false;
        seams = 0; resyncs = 0; resyncedThisStall = false;
        lastCapture = -Infinity; hold.reset();
        if (source) {startWatch();attach(generation);} else {stopWatch();phase = 'stopped'; cleanup();}
      },
      volume:function (value) {
        var next = Number(value);
        if (!Number.isFinite(next)) return;
        level = Math.max(0, Math.min(1, next)); video.volume = level; video.muted = !audio || level === 0;
        report(audioMessage());
      },
      enableAudio:function () {
        autoplayBlocked = false; advancedAt = now();
        audio = !audio; video.muted = !audio || level === 0;
        report(audioMessage());
        if (source) play();
      },
      stop:function () { source = ''; generation++; stopWatch(); phase = 'stopped'; cleanup(); },
      state:function () {
        // Read decoder counters without another decoder, frame loop or request.
        var quality = null;
        try { if (video.getVideoPlaybackQuality) quality = video.getVideoPlaybackQuality(); } catch (_) {}
        return {at:now(), mediaTimeSeconds:Number(video.currentTime)||0,
          decodedFrames:quality && Number.isFinite(quality.totalVideoFrames) ? quality.totalVideoFrames : null,
          droppedFrames:quality && Number.isFinite(quality.droppedVideoFrames) ? quality.droppedVideoFrames : null,
          paused:!!video.paused, readyState:video.readyState,
          source:source, audio:audio, volume:level, bufferedSeconds:24, bufferAheadSeconds:bufferAhead(), stalledForSeconds:Math.max(0,(now()-advancedAt)/1000),
          liveTargetSegments:8, startupBufferSeconds:startBufferSeconds, waitingForBuffer:waitingForBuffer,
          attachments:attachments, stalls:stalls, catchups:catchups, seams:seams, resyncs:resyncs,
          phase:phase, transport:transport, holding:hold.held(), errors:errors.slice()}; }
    };
  }
  return {VERSION:VERSION, create:create, loadHls:loadHls, mediaUrl:mediaUrl};
});
