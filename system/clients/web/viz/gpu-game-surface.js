/* Live native GPU frames in Chromium's compositor, with ordinary DOM stacking. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.GBoxGPUVideo = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (env) {
  "use strict";
  const doc = env.document;
  const PAD_KEYS = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    KeyX: "a", KeyZ: "b", KeyS: "x", KeyA: "y", KeyQ: "l", KeyW: "r",
    Enter: "start", ShiftRight: "select", KeyE: "l2", KeyR: "r2", KeyD: "l3", KeyF: "r3",
    Numpad8: "lup", Numpad2: "ldown", Numpad4: "lleft", Numpad6: "lright" };
  let video = null, stream = null, pending = null, current = null, generation = 0, error = null;
  let peer = null;
  const held = new Set();
  let modelLayer = null, voiceLayer = null, modelReady = false, voiceReady = false, voiceState = null, lastLayout = null;
  const modelMessages = new Map();
  let inputQueue = Promise.resolve();
  function deadline(work, phase) {
    let timer;
    return Promise.race([work, new Promise((_, reject) => {
      timer = env.setTimeout(() => reject(new Error(`Game capture timed out (${phase})`)), 6000);
    })]).finally(() => env.clearTimeout(timer));
  }
  function input(events, sid = current?.sid) {
    if (!sid || !events.length) return;
    // Preserve down/up order even when the network reply arrives out of order.
    inputQueue = inputQueue.then(async () => {
      const url = `/api/sessions/${encodeURIComponent(sid)}/input`;
      if (env.gbox) {
        const r = await env.gbox.api(url, { events });
        if (!r.ok) throw new Error(r.error);
      } else await env.api(url, { events });
    }).catch(e => { console.warn("Game input:", e.message); });
  }
  function release() {
    input([...held].map(key => ({ key, down: false })));
    held.clear();
  }
  function makeVideo() {
    const v = doc.createElement("video");
    v.className = "gbox-gpu-video"; v.muted = true; v.autoplay = true; v.playsInline = true;
    v.tabIndex = 0; v.setAttribute("aria-label", "Live game; click to control");
    Object.assign(v.style, { display: "block", width: "100%", height: "100%", objectFit: "contain",
      background: "#000", outline: "none", borderRadius: "inherit" });
    v.addEventListener("keydown", e => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const key = PAD_KEYS[e.code]; if (!key) return;
      e.preventDefault(); e.stopPropagation();
      if (!held.has(key)) { held.add(key); input([{ key, down: true }]); }
    });
    v.addEventListener("keyup", e => {
      const key = PAD_KEYS[e.code]; if (!key || !held.has(key)) return;
      e.preventDefault(); e.stopPropagation(); held.delete(key); input([{ key, down: false }]);
    });
    v.addEventListener("blur", release);
    v.addEventListener("pointerdown", e => {
      if (typeof env.closePops === "function") env.closePops(null);
      else console.log("GBOX:" + JSON.stringify({ ev: "gameclick" }));
      if (!e.ctrlKey && !e.altKey) v.focus({ preventScroll: true });
    });
    v.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (typeof env.pipMenu === "function") env.pipMenu(e.clientX, e.clientY);
      else console.log("GBOX:" + JSON.stringify({ ev: "gamecontext", x: e.clientX, y: e.clientY }));
    });
    v.addEventListener("click", e => {
      if (e.altKey) {
        const r = v.getBoundingClientRect(), content = contentRect({ x: r.left, y: r.top, w: r.width, h: r.height });
        const point = [(e.clientX - content.x) / content.w, (e.clientY - content.y) / content.h];
        if (!point.every(n => Number.isFinite(n) && n >= 0 && n <= 1)) return;
        e.preventDefault();
        if (env.gbox) env.gbox.overlay("pick", { sid: current?.sid, point });
        else console.log("GBOX:" + JSON.stringify({ ev: "gamemodelpick", sid: current?.sid, point }));
        return;
      }
      if (!e.ctrlKey) return;
      e.preventDefault();
      if (typeof env.eyePoint === "function") env.eyePoint(e.clientX, e.clientY);
      else console.log("GBOX:" + JSON.stringify({ ev: "gamepick", x: e.clientX, y: e.clientY }));
    });
    env.addEventListener("blur", release);
    return v;
  }
  function dispose() {
    generation++; release(); current = null; pending = null;
    peer?.close(); peer = null;
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null;
    if (video) { video.srcObject = null; video.remove(); video = null; }
    modelLayer?.remove(); voiceLayer?.remove(); modelLayer = voiceLayer = null; modelReady = voiceReady = false; voiceState = null;
    modelMessages.clear();
  }
  async function connect(st) {
    if (pending?.key === `${st.pid}:${st.sourceId}`) return pending.promise;
    if (current?.sourceId === st.sourceId && current.pid === st.pid && stream?.getVideoTracks()[0]?.readyState === "live") {
      current.sid = st.sid;
      if (error) throw new Error(error);
      return video;
    }
    if (st.external) throw new Error("The shared game feed is not connected");
    dispose(); error = null;
    const revision = generation, key = `${st.pid}:${st.sourceId}`;
    const promise = (async () => {
      let incoming;
      try {
        const opening = env.navigator.mediaDevices.getUserMedia({ audio: false, video: { mandatory: {
          chromeMediaSource: "desktop", chromeMediaSourceId: st.sourceId, minFrameRate: 60, maxFrameRate: 60 } } });
        // A canceled/timed-out request may resolve later; stop those tracks too.
        opening.then(s => { if (revision !== generation) s.getTracks().forEach(t => t.stop()); }, () => {});
        incoming = await deadline(opening, "source");
        if (revision !== generation) { incoming.getTracks().forEach(t => t.stop()); throw new Error("Game view changed"); }
        stream = incoming; current = { pid: st.pid, sid: st.sid, sourceId: st.sourceId };
        stream.getVideoTracks()[0].contentHint = "motion";
        video = makeVideo(); video.srcObject = stream;
        stream.getVideoTracks()[0].addEventListener("ended", () => { error = "The game capture source ended"; });
        await deadline(video.play(), "first frame");
        if (revision !== generation) throw new Error("Game view changed");
        if (!video.videoWidth || !video.videoHeight) throw new Error("No decoded game frame");
        return video;
      } catch (e) {
        incoming?.getTracks().forEach(t => t.stop());
        if (revision === generation) dispose();
        throw e;
      }
    })();
    pending = { key, promise };
    try { return await promise; } finally { if (pending?.promise === promise) pending = null; }
  }
  async function ice(pc) {
    if (pc.iceGatheringState === "complete") return;
    await new Promise(resolve => {
      const done = () => { if (pc.iceGatheringState === "complete") finish(); };
      const finish = () => { env.clearTimeout(timer); pc.removeEventListener("icegatheringstatechange", done); resolve(); };
      const timer = env.setTimeout(finish, 2000);
      pc.addEventListener("icegatheringstatechange", done); done();
    });
  }
  async function offer() {
    if (!stream || error) throw new Error("No game capture to share");
    peer?.close(); peer = new env.RTCPeerConnection({ iceServers: [] });
    for (const track of stream.getVideoTracks()) peer.addTrack(track, stream);
    // Prefer hardware-capable H.264 when Chromium exposes it; keep other codecs
    // as fallbacks. This is a local feed between the app's two renderers.
    const codecs = env.RTCRtpSender?.getCapabilities("video")?.codecs;
    if (codecs?.some(c => c.mimeType === "video/H264")) {
      const sorted = [...codecs].sort((a, b) => Number(b.mimeType === "video/H264") - Number(a.mimeType === "video/H264"));
      peer.getTransceivers()[0].setCodecPreferences(sorted);
    }
    await peer.setLocalDescription(await peer.createOffer()); await ice(peer);
    return peer.localDescription.toJSON();
  }
  async function receive(st, description) {
    dispose(); error = null;
    const revision = generation, pc = peer = new env.RTCPeerConnection({ iceServers: [] });
    let accept, reject;
    const waiting = new Promise((yes, no) => { accept = yes; reject = no; });
    const promise = deadline(waiting, "shared feed").catch(e => { if (revision === generation) dispose(); throw e; });
    // The first frame arrives after the caller returns our SDP answer to the host.
    promise.catch(() => {}); pending = { key: `${st.pid}:${st.sourceId}`, promise };
    pc.addEventListener("track", async e => {
      try {
        if (revision !== generation) { e.track.stop(); return; }
        stream = e.streams[0]; current = { pid: st.pid, sid: st.sid, sourceId: st.sourceId };
        video = makeVideo(); video.srcObject = stream;
        e.track.addEventListener("ended", () => { error = "The shared game feed ended"; });
        await deadline(video.play(), "shared first frame");
        if (revision !== generation) throw new Error("Game view changed");
        if (!video.videoWidth) throw new Error("No shared game frame");
        accept(video); if (pending?.promise === promise) pending = null;
      } catch (e) { reject(e); }
    });
    pc.addEventListener("connectionstatechange", () => {
      if (revision === generation && ["failed", "closed", "disconnected"].includes(pc.connectionState)) error = "The shared game feed disconnected";
    });
    await pc.setRemoteDescription(description); await pc.setLocalDescription(await pc.createAnswer()); await ice(pc);
    return pc.localDescription.toJSON();
  }
  async function answer(description) {
    await peer.setRemoteDescription(description);
    const sender = peer.getSenders()[0], params = sender.getParameters();
    if (params.encodings?.length) {
      for (const encoding of params.encodings) { encoding.maxBitrate = 16000000; encoding.maxFramerate = 60; encoding.priority = "high"; }
      params.degradationPreference = "maintain-framerate";
      await sender.setParameters(params);
    }
  }
  async function quality() {
    if (!peer) return null;
    const rows = await peer.getStats(); let videoStats;
    rows.forEach(s => { if (["outbound-rtp", "inbound-rtp"].includes(s.type) && s.kind === "video") videoStats = s; });
    if (!videoStats) return { connection: peer.connectionState };
    const codec = rows.get(videoStats.codecId);
    return { connection: peer.connectionState, codec: codec?.mimeType, width: videoStats.frameWidth, height: videoStats.frameHeight,
      fps: videoStats.framesPerSecond, frames: videoStats.framesEncoded ?? videoStats.framesDecoded,
      limitation: videoStats.qualityLimitationReason, encoder: videoStats.encoderImplementation,
      decoder: videoStats.decoderImplementation, hardwareEncoder: videoStats.powerEfficientEncoder,
      hardwareDecoder: videoStats.powerEfficientDecoder };
  }
  async function sync(st) {
    const v = await connect(st);
    if (st.host === "root") {
      if (v.parentElement !== doc.body) doc.body.append(v);
      const r = st.rect;
      Object.assign(v.style, { position: "fixed", zIndex: "35", left: (r?.x || 0) + "px", top: (r?.y || 0) + "px",
        width: (r?.w || 1) + "px", height: (r?.h || 1) + "px", display: st.visible ? "block" : "none" });
      v.id = "gpu-game";
    } else {
      const slot = doc.getElementById("nativeslot");
      if (slot?.dataset.sid === st.sid) {
        slot.dataset.surface = "gpu";
        slot.style.position = "relative";
        Object.assign(v.style, { position: "absolute", inset: "0", width: "100%", height: "100%", display: st.visible ? "block" : "none" });
        if (v.parentElement !== slot) { release(); slot.append(v); }
      } else { release(); v.remove(); }
    }
    // Rebuilding the session panel removes its previous slot. Chromium pauses a
    // removed video even though the MediaStream and local peer remain healthy.
    if (v.paused) await deadline(v.play(), "resume view");
    lastLayout = st; placeLayers();
    return stats();
  }
  function snapshot(maxHeight = 0) {
    if (!video?.videoWidth || error || stream?.getVideoTracks()[0]?.readyState !== "live") return null;
    const c = doc.createElement("canvas"); c.height = maxHeight ? Math.min(maxHeight, video.videoHeight) : video.videoHeight;
    c.width = Math.round(video.videoWidth * c.height / video.videoHeight);
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    return c.toDataURL("image/png");
  }
  function layer(url) {
    const frame = doc.createElement("iframe"); frame.src = url; frame.tabIndex = -1;
    frame.setAttribute("aria-hidden", "true");
    Object.assign(frame.style, { border: "0", background: "transparent", colorScheme: "dark", pointerEvents: "none" });
    return frame;
  }
  function contentRect(r) {
    const scale = Math.min(r.w / video.videoWidth, r.h / video.videoHeight);
    const w = video.videoWidth * scale, h = video.videoHeight * scale;
    return { x: r.x + (r.w - w) / 2, y: r.y + (r.h - h) / 2, w, h };
  }
  function placeLayers() {
    for (const frame of [modelLayer, voiceLayer]) {
      if (!frame || !video) continue;
      const visible = lastLayout?.visible && video.parentElement;
      frame.style.display = visible ? "block" : "none";
      if (lastLayout?.host === "root") {
        const r = contentRect(lastLayout.rect || { x: 0, y: 0, w: 1, h: 1 });
        Object.assign(frame.style, { position: "fixed", left: (r.x || 0) + "px", top: (r.y || 0) + "px",
          width: (r.w || 1) + "px", height: (r.h || 1) + "px", zIndex: "36" });
      } else {
        const r = contentRect({ x: 0, y: 0, w: video.clientWidth, h: video.clientHeight });
        Object.assign(frame.style, { position: "absolute", left: r.x + "px", top: r.y + "px",
          width: r.w + "px", height: r.h + "px", zIndex: "1" });
      }
      if (video.parentElement && frame.parentElement !== video.parentElement) video.parentElement.append(frame);
    }
  }
  function overlay(m, url) {
    if (m.type === "stop") { modelLayer?.remove(); modelLayer = null; modelReady = false; modelMessages.clear(); return; }
    if (m.type === "reset") modelMessages.delete("box");
    modelMessages.set(m.type, m);
    if (!modelLayer && url) { modelLayer = layer(url); placeLayers(); }
    if (modelReady) modelLayer?.contentWindow.postMessage({ gboxSwap: m }, new URL(modelLayer.src).origin);
  }
  function voice(st, url) {
    if (!st.on) { voiceLayer?.remove(); voiceLayer = null; voiceReady = false; voiceState = null; return; }
    voiceState = { level: st.level, beat: st.beat };
    if (!voiceLayer && url) {
      const frame = voiceLayer = layer(url); frame.style.opacity = "0.42";
      frame.addEventListener("load", () => {
        if (voiceLayer !== frame) return;
        voiceReady = true;
        frame.contentWindow.postMessage({ gboxVoice: voiceState }, new URL(frame.src).origin);
      });
      placeLayers();
    }
    if (voiceReady) voiceLayer?.contentWindow.postMessage({ gboxVoice: voiceState }, new URL(voiceLayer.src).origin);
  }
  env.addEventListener("message", e => {
    if (!modelLayer || e.source !== modelLayer.contentWindow || e.origin !== new URL(modelLayer.src).origin || !e.data?.gboxSwapStatus) return;
    const status = e.data.gboxSwapStatus;
    if (status.ready) {
      modelReady = true;
      modelMessages.forEach(m => modelLayer.contentWindow.postMessage({ gboxSwap: m }, new URL(modelLayer.src).origin));
    }
    if (env.gbox) env.gbox.overlay("surface-status", status);
    else console.log("GBOX:" + JSON.stringify({ ev: "gameoverlaystatus", status }));
  });
  function stats() {
    return { ready: !!video?.videoWidth && !error, pid: current?.pid, sourceId: current?.sourceId,
      width: video?.videoWidth, height: video?.videoHeight, frames: video?.getVideoPlaybackQuality().totalVideoFrames,
      mediaTime: video?.currentTime, track: stream?.getVideoTracks()[0]?.readyState, paused: video?.paused, error };
  }
  env.addEventListener("beforeunload", dispose);
  return { sync, dispose, snapshot, stats, quality, overlay, voice, offer, receive, answer,
    focus: () => video?.focus({ preventScroll: true }), release, PAD_KEYS };
});
