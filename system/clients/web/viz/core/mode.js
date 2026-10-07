// Base class for visualizer modes. Lifecycle: init(ctx) activate() update(state, dt, realDt) resize(w,h,W,H) deactivate() dispose()
// ctx = { renderer, pal (shared palette uniforms {uBg0,uBg1,uC1,uC2,uC3,uHi}), quality, qmult, w, h, W, H, pr }
// this.params = preset values with the global HUD multipliers applied (intensity, speed, audioSensitivity, smoothing, bloom,
// opacity, complexity, motionAmount); `dt` passed to update() is already multiplied by params.speed.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { disposeObject } from "./util.js";

export class Mode {
  init(ctx) {
    this.ctx = ctx;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(50, ctx.w / ctx.h, 0.1, 400);
    this.camera.position.set(0, 0, 10);
    this.t = 0; this._pb = 0; this.particles = 0;
  }
  activate() {}
  deactivate() {}
  update(s, dt, rdt) {}
  // returns the beat strength on a fresh beat impulse (rising edge), else 0
  beatHit(s, th = 0.25) { const h = s.beat - this._pb > th ? s.beat : 0; this._pb = s.beat; return h; }
  resize(w, h, W, H) { if (this.camera.isPerspectiveCamera) { this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); } }
  setQuality(q, mult) {}
  render(r, target) { r.setRenderTarget(target); r.render(this.scene, this.camera); }
  stats() {
    let objects = 0;
    this.scene.traverse((o) => { if (o.visible && (o.isMesh || o.isPoints || o.isLine)) objects++; });
    return { objects, particles: this.particles | 0 };
  }
  dispose() { disposeObject(this.scene); }
}
