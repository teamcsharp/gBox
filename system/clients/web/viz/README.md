# gBox visualizer (`/viz/`)

Procedural Three.js (r160, CDN) visualizer with 10 modes. Plain ES modules, no build step.
Used as the loading-screen "screensaver" between titles; `index.html` is a standalone full-window demo
(keys: `1`-`0` modes, `H` or `` ` `` HUD, `O` radio overlay, `M` mic, `D` demo; right-click for the picker; `?hud` opens the HUD).

## API (`viz.js`)

```js
import { createViz, attachPicker, readVizPref, MODES } from "/viz/viz.js";

const viz = await createViz(canvas, {
  mode: readVizPref(),        // "random" | mode id
  palette: "PlayStation Blue",// | "Neon" | "Monochrome" | "Radio Night"  (case/space-insensitive)
  quality: "auto",            // | "low" | "medium" | "high" | "ultra"   (auto steps down when FPS < 45 for 3 s)
  provider: "demo",           // | "mic" | "external"
  wsUrl: null,                // for provider "external"
  hud: false, keys: false,    // debug HUD / keyboard shortcuts
  cycleSecs: 0,               // > 0: auto-rotate random modes with crossfades
});
attachPicker(canvas, viz);    // right-click menu; returns the stored pref ("random" | id)

viz.setMode("random" | id, { transition: "crossfade" | "dissolve" | "fade" });  // returns Promise<id>
viz.getMode(); viz.list(); viz.start(); viz.stop(); viz.resize(); viz.dispose();
viz.setProvider("demo" | "mic" | "external", { wsUrl });                       // Promise; mic needs a user gesture + permission
viz.setPalette(name); viz.setQuality(q); viz.toggleHud();
viz.push({ speechActivity: 0.7, stationActivity: 0.4, beat: 1, loadProgress: 0.3 });
```

`"random"` picks a mode different from the last one used (stored in `localStorage.gbox_viz_last`), so calling
`createViz`/`setMode("random")` per title cycles randomly between titles. The picker stores its choice in
`localStorage.gbox_viz_mode` (palette in `gbox_viz_mode_palette`). Extras: `readVizPref(key)`, `pickRandomMode()`,
`viz.state` (live telemetry), `viz.requestedMode`, `viz.getPalette()`, `viz.getQuality()`, `viz.manager`.
`createViz` throws if WebGL is unavailable; the canvas keeps its CSS size (the renderer follows it via ResizeObserver).

## Telemetry (`viz.state`, `push()`)

`rms peak bass mid treble beat onset speechActivity stationActivity energy time fft(Float32Array[64], log-spaced 20 Hz-20 kHz)`,
all 0..1 and already smoothed (bass slow, treble fast, beat = instant attack + exponential decay, peak hold,
noise floor + auto gain). `push()` merges external values: numeric `rms/bass/mid/treble/speechActivity/stationActivity`
act as a floor for ~2.5 s, `beat > 0` fires a beat impulse, any other field (e.g. `loadProgress`, `title`) is copied
onto the state. The `external` provider also accepts the same JSON over WebSocket (optionally with `fft: [...]`);
without spectrum data it synthesises one from the pushed activity levels so modes still react.

## Adding a mode

1. Create `modes/<id>.js` exporting a default class extending `Mode` (`core/mode.js`):
   `init(ctx)` (call `super.init(ctx)`; build `this.scene` / `this.camera`, allocate everything once),
   `update(state, dt, realDt)` (no per-frame allocations; `dt` is already scaled by the preset speed),
   `resize(w, h, W, H)`, `setQuality(name, mult)` (use draw ranges / instance counts, don't reallocate),
   optional `activate() / deactivate() / render(renderer, target) / stats()`.
2. Use the shared palette uniforms by spreading `ctx.pal` into your ShaderMaterial uniforms
   (`uBg0 uBg1 uC1 uC2 uC3 uHi`, declare with `PAL_DECL` from `core/glsl.js`); they blend automatically on palette change.
   `makeBackdrop()`, `makeFFTTexture()`, `NOISE3`, `HASH` are in `core/glsl.js`; `Spring`, `noise2`, `rng` in `core/util.js`.
3. Add `{id, n, name}` to `MODES` in `viz.js` and a preset in `presets.json`
   (`intensity speed audioSensitivity smoothing bloom opacity complexity motionAmount`).

Modes are lazily imported and initialised on first use, then kept (GPU resources are not rebuilt on switches).
Keep the screen centre calm (the loader draws the title/logo there) and give every mode a moving idle state.
