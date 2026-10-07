// SignalProcessor: raw provider frame -> smoothed VisualizerState (a general telemetry bus).
export const NB = 64; // log-spaced spectrum bins, 20 Hz .. 20 kHz

export function createState() {
  return {
    rms: 0, peak: 0, bass: 0, mid: 0, treble: 0, beat: 0, onset: false,
    speechActivity: 0, stationActivity: 0, energy: 0, time: 0, fft: new Float32Array(NB),
  };
}
export function createRaw() { return { fft: new Float32Array(NB), rms: 0, speech: -1, station: -1 }; }

const CORE = new Set(["rms", "peak", "bass", "mid", "treble", "beat", "onset", "speechActivity", "stationActivity", "energy", "time", "fft"]);
const OVERRIDABLE = ["rms", "bass", "mid", "treble", "speechActivity", "stationActivity"];
const BASS_END = 23, MID_END = 48; // bins: < ~250 Hz, ~250 Hz..4 kHz, above  (bin i = 20 Hz * 1000^(i/63))

const k = (dt, tau) => 1 - Math.exp(-dt / tau);
const asym = (cur, target, att, dec, dt) => cur + (target - cur) * k(dt, target > cur ? att : dec);

export class SignalProcessor {
  constructor() {
    this.state = createState();
    this.floor = new Float32Array(NB).fill(0.03);
    this.prev = new Float32Array(NB);
    this.x = new Float32Array(NB);
    this.runMax = 0.2; this.rmsMax = 0.1; this.fluxAvg = 0.05;
    this.lastOnset = -1; this.peakHold = 0; this.t = 0; this.pendingBeat = 0;
    this.ext = {}; // field -> {v, t}
    for (const f of OVERRIDABLE) this.ext[f] = { v: 0, t: -99 };
    this.speechD = 0; this.stationD = 0;
  }

  // merge external telemetry. numeric core fields act as "at least this" for ~2.5 s; beat triggers an impulse;
  // any other field (e.g. loadProgress, title) is copied onto the state as-is.
  push(obj) {
    if (!obj || typeof obj !== "object") return;
    for (const key in obj) {
      const v = obj[key];
      if (key === "beat") { const b = +v; if (b > 0) this.pendingBeat = Math.max(this.pendingBeat, Math.min(1, b)); }
      else if (this.ext[key]) { if (typeof v === "number" && isFinite(v)) { this.ext[key].v = v; this.ext[key].t = this.t; } }
      else if (!CORE.has(key)) this.state[key] = v;
    }
  }
  extVal(key, maxAge = 2.5) { const e = this.ext[key]; return e && this.t - e.t < maxAge ? e.v : -1; }

  process(raw, dt) {
    const S = this.state, fft = raw.fft, x = this.x;
    this.t += dt; S.time = this.t; S.onset = false;

    // noise floor tracking (fast down, very slow up) + auto gain
    let fmax = 0;
    for (let i = 0; i < NB; i++) {
      const v = fft[i] || 0, f = this.floor[i];
      this.floor[i] = v < f ? f + (v - f) * k(dt, 0.25) : f + (v - f) * k(dt, 40);
      const y = Math.max(0, v - this.floor[i] * 1.1);
      x[i] = y; if (y > fmax) fmax = y;
    }
    this.runMax = Math.max(fmax, this.runMax * Math.exp(-dt / 20));
    const gain = 0.95 / Math.max(this.runMax, 0.3); // the floor keeps quiet passages quiet and silence from becoming noise

    let flux = 0, b = 0, m = 0, t = 0;
    for (let i = 0; i < NB; i++) {
      const y = Math.min(1, x[i] * gain);
      const d = y - this.prev[i]; if (d > 0) flux += d * (i < BASS_END ? 1.6 : i < MID_END ? 1 : 0.5);
      this.prev[i] = y;
      S.fft[i] = asym(S.fft[i], y, 0.03, 0.2, dt);
      if (i < BASS_END) b += y; else if (i < MID_END) m += y; else t += y;
    }
    b /= BASS_END; m /= MID_END - BASS_END; t /= NB - MID_END;

    // rms with its own dynamic range
    const r = raw.rms || 0;
    this.rmsMax = Math.max(r, this.rmsMax * Math.exp(-dt / 20));
    let rmsT = Math.min(1, r / Math.max(this.rmsMax, 0.2));

    // derived speech / station activity unless the provider supplies them
    this.speechD = raw.speech >= 0 ? raw.speech : asym(this.speechD, Math.min(1, Math.max(0, (m - 0.6 * b) * 2.2)), 0.2, 0.8, dt);
    this.stationD = raw.station >= 0 ? raw.station : asym(this.stationD, rmsT, 1.5, 4, dt);

    // fresh external values are a floor for the derived ones
    let bT = b * 1.25, mT = m * 1.35, tT = t * 1.6, spT = this.speechD, stT = this.stationD, e;
    if ((e = this.extVal("rms")) >= 0) rmsT = Math.max(rmsT, e);
    if ((e = this.extVal("bass")) >= 0) bT = Math.max(bT, e);
    if ((e = this.extVal("mid")) >= 0) mT = Math.max(mT, e);
    if ((e = this.extVal("treble")) >= 0) tT = Math.max(tT, e);
    if ((e = this.extVal("speechActivity")) >= 0) spT = Math.max(spT, e);
    if ((e = this.extVal("stationActivity")) >= 0) stT = Math.max(stT, e);

    // per-property smoothing: bass slow/slow, treble fast/fast, rms moderate
    S.bass = asym(S.bass, Math.min(1, bT), 0.12, 0.45, dt);
    S.mid = asym(S.mid, Math.min(1, mT), 0.06, 0.22, dt);
    S.treble = asym(S.treble, Math.min(1, tT), 0.02, 0.08, dt);
    S.rms = asym(S.rms, rmsT, 0.07, 0.3, dt);
    S.speechActivity = asym(S.speechActivity, Math.min(1, spT), 0.25, 1.2, dt);
    S.stationActivity = asym(S.stationActivity, Math.min(1, stT), 0.8, 3, dt);

    // peak hold
    if (S.rms >= S.peak) { S.peak = S.rms; this.peakHold = 0.5; }
    else if ((this.peakHold -= dt) < 0) S.peak = Math.max(S.rms, S.peak - dt * 0.6);

    // onset detection: spectral flux vs adaptive threshold; beat = instant attack, exponential decay
    S.beat *= Math.exp(-dt * 5);
    const th = this.fluxAvg * 1.7 + 0.35;
    if (flux > th && this.t - this.lastOnset > 0.18) {
      this.lastOnset = this.t; S.onset = true;
      S.beat = Math.max(S.beat, Math.min(1, 0.55 + 0.45 * (flux / th - 1)));
    }
    this.fluxAvg += (flux - this.fluxAvg) * k(dt, 0.8);
    if (this.pendingBeat > 0) { S.beat = Math.max(S.beat, this.pendingBeat); S.onset = true; this.pendingBeat = 0; }

    S.energy = Math.min(1, 0.5 * S.rms + 0.3 * S.bass + 0.2 * S.mid);
    return S;
  }
}
