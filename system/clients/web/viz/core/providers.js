// Signal providers. Each fills a raw frame {fft: Float32Array(NB) 0..1, rms, speech (-1 = unknown), station (-1)}.
import { NB } from "./signal.js";
import { rng } from "./util.js";

const FREQ = new Float32Array(NB);
for (let i = 0; i < NB; i++) FREQ[i] = 20 * Math.pow(1000, i / (NB - 1));
const LN2 = Math.log(2);
const g = (f, c, w) => { const d = Math.log(f / c) / LN2 / w; return Math.exp(-d * d); }; // gaussian in octaves

// ---------------------------------------------------------------- demo: synthetic station activity
const SCENES = ["silence", "conversation", "energetic", "music", "bass", "transients", "ambience"];

export class DemoProvider {
  constructor() {
    this.kind = "demo"; this.T = 0; this.r = rng((Date.now() & 0xffff) + 1);
    this.cur = "ambience"; this.next = null; this.st = 0; this.dur = 7; this.fade = 0;
    this.A = new Float32Array(NB); this.B = new Float32Array(NB);
    this.ia = { speech: 0, station: 0 }; this.ib = { speech: 0, station: 0 };
    this.hit = 0; this.hitF = 400; this.sib = 0;
  }
  start() {} stop() {}
  get scene() { return this.next ? `${this.cur}>${this.next}` : this.cur; }
  sample(t, dt, raw) {
    const r = this.r;
    this.T += dt; this.st += dt;
    if (!this.next && this.st > this.dur) {
      let n; do n = SCENES[(r() * SCENES.length) | 0]; while (n === this.cur);
      this.next = n; this.fade = 0;
    }
    if (this.next) {
      this.fade += dt / 2.5;
      if (this.fade >= 1) { this.cur = this.next; this.next = null; this.st = 0; this.dur = (this.cur === "silence" ? 4 : 9) + r() * 8; this.fade = 0; }
    }
    this.hit *= Math.exp(-dt * 10);
    if (r() < dt * 1.6) { this.hit = 0.6 + 0.4 * r(); this.hitF = 80 * Math.pow(100, r()); }
    this.sib *= Math.exp(-dt * 14);
    if (r() < dt * 2.5) this.sib = 0.5 + 0.5 * r();

    const out = raw.fft;
    this.gen(this.cur, this.A, this.ia);
    let speech = this.ia.speech, station = this.ia.station;
    if (this.next) {
      this.gen(this.next, this.B, this.ib);
      const f = this.fade * this.fade * (3 - 2 * this.fade);
      for (let i = 0; i < NB; i++) out[i] = this.A[i] * (1 - f) + this.B[i] * f;
      speech += (this.ib.speech - speech) * f; station += (this.ib.station - station) * f;
    } else out.set(this.A);
    let ss = 0;
    for (let i = 0; i < NB; i++) { out[i] += 0.01 + 0.012 * r(); ss += out[i] * out[i]; }
    raw.rms = Math.sqrt(ss / NB) * 1.3; raw.speech = speech; raw.station = station;
  }
  gen(name, o, info) {
    const T = this.T;
    o.fill(0); info.speech = 0;
    switch (name) {
      case "silence": info.station = 0.05; break;
      case "conversation":
      case "energetic": {
        const fast = name === "energetic";
        const syl = Math.pow(Math.max(0, Math.sin(T * 6.2832 * (fast ? 5.6 : 4.1) + 1.7 * Math.sin(T * 1.3))), 2);
        const gate = fast ? (Math.sin(T * 0.7) > -0.8 ? 1 : 0) : (Math.sin(T * 0.9) + 0.4 * Math.sin(T * 2.3) > -0.3 ? 1 : 0);
        const v = Math.sin(T * 0.23) > 0 ? 1 : 1.3; // two speakers
        const amp = (fast ? 0.85 : 0.55) * gate * (0.2 + 0.8 * syl);
        for (let i = 0; i < NB; i++) {
          const f = FREQ[i];
          o[i] = amp * (0.9 * g(f, 140 * v, 0.5) + 0.7 * g(f, 550 * v, 0.6) + 0.5 * g(f, 1500 * v, 0.6) + 0.3 * g(f, 2600, 0.5)) +
            (fast ? this.sib * 0.5 * g(f, 7000, 0.7) * gate : 0);
        }
        info.speech = gate * 0.9; info.station = fast ? 0.6 : 0.4;
        break;
      }
      case "music": {
        const bp = T * 118 / 60, ph = bp % 1, n = Math.floor(bp);
        const kick = Math.exp(-ph * 9), snare = n % 2 === 1 ? Math.exp(-ph * 14) : 0, hat = Math.exp(-((bp * 2) % 1) * 22);
        const bl = 0.5 + 0.5 * Math.sin(bp * Math.PI * 0.5), pad = 0.75 + 0.25 * Math.sin(T * 0.6);
        for (let i = 0; i < NB; i++) {
          const f = FREQ[i];
          o[i] = kick * 0.95 * g(f, 55, 0.9) + 0.35 * bl * g(f, 110, 0.5) + snare * 0.6 * g(f, 1800, 1.6) + hat * 0.4 * g(f, 9000, 0.7) +
            0.28 * pad * (g(f, 330, 0.8) + 0.7 * g(f, 880, 0.7) + 0.5 * g(f, 1320, 0.5));
        }
        info.station = 0.85;
        break;
      }
      case "bass": {
        const bp = T * 70 / 60, ph = bp % 1, kick = Math.exp(-ph * 6);
        const wob = Math.pow(0.5 + 0.5 * Math.sin(T * 6.2832 * (70 / 60) * 2), 2);
        for (let i = 0; i < NB; i++) {
          const f = FREQ[i];
          o[i] = kick * g(f, 48, 0.8) + wob * 0.85 * g(f, 70, 0.6) + 0.18 * wob * g(f, 250, 0.8) + 0.07 * g(f, 5000, 1) * kick;
        }
        info.station = 0.9;
        break;
      }
      case "transients":
        for (let i = 0; i < NB; i++) { const f = FREQ[i]; o[i] = this.hit * 0.9 * g(f, this.hitF, 2.2) + 0.05 * g(f, 400, 1.5); }
        info.station = 0.45;
        break;
      default: { // ambience
        const c = 300 * Math.pow(8, 0.5 + 0.5 * Math.sin(T * 0.13));
        for (let i = 0; i < NB; i++) {
          const f = FREQ[i];
          o[i] = 0.22 * g(f, c, 1.1) + 0.14 * g(f, c * 2.7, 0.8) * (0.5 + 0.5 * Math.sin(T * 0.31)) + 0.06 * g(f, 6000, 1.2) * (0.5 + 0.5 * Math.sin(T * 0.71));
        }
        info.station = 0.25;
      }
    }
  }
}

// ---------------------------------------------------------------- microphone (only when asked)
export class MicrophoneProvider {
  constructor() { this.kind = "mic"; this.ready = false; this.error = null; }
  async start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ac = new AC();
    if (this.ac.state === "suspended") await this.ac.resume().catch(() => {});
    this.stream = stream;
    this.src = this.ac.createMediaStreamSource(stream);
    this.an = this.ac.createAnalyser(); this.an.fftSize = 2048; this.an.smoothingTimeConstant = 0.35;
    this.src.connect(this.an);
    this.freq = new Float32Array(this.an.frequencyBinCount); this.td = new Float32Array(this.an.fftSize);
    const n = this.freq.length, nyq = this.ac.sampleRate / 2, half = Math.pow(1000, 0.5 / (NB - 1));
    this.lo = new Uint16Array(NB); this.hi = new Uint16Array(NB);
    for (let i = 0; i < NB; i++) {
      const lo = Math.max(1, Math.floor((FREQ[i] / half) / nyq * n)), hi = Math.min(n - 1, Math.max(lo + 1, Math.ceil((FREQ[i] * half) / nyq * n)));
      this.lo[i] = lo; this.hi[i] = hi;
    }
    this.ready = true;
  }
  stop() {
    this.ready = false;
    try { this.stream && this.stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
    try { this.ac && this.ac.close(); } catch (e) {}
  }
  sample(t, dt, raw) {
    raw.speech = -1; raw.station = -1;
    if (!this.ready) { raw.fft.fill(0); raw.rms = 0; return; }
    this.an.getFloatFrequencyData(this.freq); this.an.getFloatTimeDomainData(this.td);
    for (let i = 0; i < NB; i++) {
      let m = -200;
      for (let j = this.lo[i]; j < this.hi[i]; j++) if (this.freq[j] > m) m = this.freq[j];
      const v = (m + 95) / 65; raw.fft[i] = v <= 0 ? 0 : v >= 1 ? 1 : v * v;
    }
    let ss = 0; for (let i = 0; i < this.td.length; i++) ss += this.td[i] * this.td[i];
    raw.rms = Math.min(1, Math.sqrt(ss / this.td.length) * 3);
  }
}

// ---------------------------------------------------------------- external: WebSocket JSON states (and/or push())
// Messages: {"fft":[...], "rms":0.3, "bass":..., "mid":..., "treble":..., "beat":1, "speechActivity":0.7, "stationActivity":0.4, ...}
// Without fft/bands, a pseudo-spectrum is synthesised from speech/station activity so the visuals still react.
export class ExternalProvider {
  constructor(url, signal) {
    this.kind = "external"; this.url = url || null; this.signal = signal;
    this.fftIn = new Float32Array(NB); this.hasFft = false; this.age = 99; this.retry = 1; this.closed = true; this.T = 0;
  }
  start() { this.closed = false; this.connect(); }
  connect() {
    if (!this.url || this.closed) return;
    let ws;
    try { ws = this.ws = new WebSocket(this.url); } catch (e) { this.error = e; return; }
    ws.onopen = () => { this.retry = 1; };
    ws.onmessage = (e) => { try { this.handle(JSON.parse(e.data)); } catch (err) {} };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
    ws.onclose = () => { if (!this.closed) this.timer = setTimeout(() => this.connect(), Math.min(15000, 1000 * (this.retry *= 2))); };
  }
  stop() { this.closed = true; clearTimeout(this.timer); try { this.ws && this.ws.close(); } catch (e) {} this.ws = null; }
  handle(m) {
    if (!m || typeof m !== "object") return;
    if (Array.isArray(m.fft) && m.fft.length) {
      const L = m.fft.length;
      for (let i = 0; i < NB; i++) this.fftIn[i] = +m.fft[Math.min(L - 1, Math.floor(i / NB * L))] || 0;
      this.hasFft = true; this.age = 0;
    }
    const { fft, ...rest } = m;
    this.signal.push(rest); // bands, beat, activities, arbitrary telemetry
  }
  sample(t, dt, raw) {
    this.T += dt; this.age += dt;
    raw.speech = -1; raw.station = -1;
    const S = this.signal;
    if (this.hasFft && this.age < 2) { raw.fft.set(this.fftIn); }
    else {
      const bass = Math.max(0, S.extVal("bass")), mid = Math.max(0, S.extVal("mid")), tre = Math.max(0, S.extVal("treble"));
      const sp = Math.max(0, S.extVal("speechActivity")), st = Math.max(0, S.extVal("stationActivity"));
      const syl = Math.pow(Math.max(0, Math.sin(this.T * 6.2832 * 4.3 + 1.7 * Math.sin(this.T * 1.3))), 2);
      for (let i = 0; i < NB; i++) {
        const f = FREQ[i];
        raw.fft[i] = bass * g(f, 70, 1.2) + mid * g(f, 1000, 1.5) + tre * g(f, 8000, 1.2) +
          sp * (0.2 + 0.8 * syl) * 0.6 * (g(f, 160, 0.6) + 0.7 * g(f, 700, 0.7) + 0.4 * g(f, 2200, 0.6)) + st * 0.25 * g(f, 400, 2.5);
      }
    }
    let ss = 0; for (let i = 0; i < NB; i++) ss += raw.fft[i] * raw.fft[i];
    raw.rms = Math.sqrt(ss / NB) * 1.3;
  }
}
