// 4 Geometric Space: floating polyhedra / rings / hollow cubes at depth, glass + wireframe + emissive edges,
// a subtle energy ribbon, beat impulses spawn fragments.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { Mode } from "../core/mode.js";
import { NOISE3, PAL_DECL, makeBackdrop } from "../core/glsl.js";
import { Spring, rng } from "../core/util.js";

const NMAX = 40, FRAG = 160, ZFAR = -48, ZNEAR = 7;

const RIB_VS = `${NOISE3} uniform float uTime, uAmp; varying float vV, vU;
void main(){
  float x = (uv.x - 0.5) * 70.0, v = uv.y - 0.5;
  float y = -2.6 + sin(x * 0.11 + uTime * 0.4) * 0.8 * uAmp + snoise(vec3(x * 0.05, uTime * 0.1, 3.0)) * 0.7;
  float z = -12.0 + sin(x * 0.07 - uTime * 0.25) * 3.0;
  float a = sin(x * 0.09 + uTime * 0.3) * 1.4;
  vec3 p = vec3(x, y, z) + vec3(0.0, cos(a), sin(a)) * v * 0.5;
  vV = v * 2.0; vU = uv.x;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const RIB_FS = `${PAL_DECL} uniform float uAlpha; varying float vV, vU;
void main(){ float a = abs(vV); float e = exp(-a * a * 6.0) * 0.5 + smoothstep(0.8, 1.0, a) * 0.25;
  gl_FragColor = vec4(mix(uC2, uC3, vU), e * uAlpha * smoothstep(0.0, 0.15, vU) * smoothstep(1.0, 0.85, vU)); }`;

export default class GeometricSpace extends Mode {
  init(ctx) {
    super.init(ctx);
    this.camera.fov = 55; this.camera.far = 120; this.camera.position.set(0, 0, 8);
    this.scene.add(this.bg = makeBackdrop(ctx.pal));
    this.scene.fog = new THREE.FogExp2(new THREE.Color(), 0.035);
    const P = ctx.pal;
    this.amb = new THREE.AmbientLight(new THREE.Color(), 0.6);
    this.dir = new THREE.DirectionalLight(new THREE.Color(1, 1, 1), 1.6); this.dir.position.set(3, 5, 6);
    this.pl1 = new THREE.PointLight(new THREE.Color(), 60, 40, 1.6); this.pl1.position.set(-7, 3, 2);
    this.pl2 = new THREE.PointLight(new THREE.Color(), 60, 40, 1.6); this.pl2.position.set(7, -3, -3);
    this.scene.add(this.amb, this.dir, this.pl1, this.pl2);

    const geos = [
      new THREE.IcosahedronGeometry(1, 0), new THREE.OctahedronGeometry(1.1, 0), new THREE.TorusGeometry(1, 0.05, 8, 64),
      new THREE.BoxGeometry(1.4, 1.4, 1.4), new THREE.DodecahedronGeometry(1, 0), new THREE.TetrahedronGeometry(1.2, 0),
    ];
    const edges = geos.map((g, i) => (i === 2 ? null : new THREE.EdgesGeometry(g, 1)));
    this.innerEdges = new THREE.EdgesGeometry(new THREE.BoxGeometry(0.8, 0.8, 0.8));
    const add = THREE.AdditiveBlending;
    this.m = {
      glass: new THREE.MeshStandardMaterial({ transparent: true, opacity: 0.28, metalness: 0.3, roughness: 0.12, flatShading: true, depthWrite: false, side: THREE.DoubleSide }),
      solid: new THREE.MeshStandardMaterial({ metalness: 0.65, roughness: 0.28, flatShading: true }),
      ring: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9, blending: add, depthWrite: false }),
      e1: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.95, blending: add, depthWrite: false }),
      e2: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.95, blending: add, depthWrite: false }),
      e3: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.9, blending: add, depthWrite: false }),
    };
    const r = this.r = rng(21);
    this.aspect = ctx.w / ctx.h;
    this.objs = [];
    for (let i = 0; i < NMAX; i++) {
      const type = i % 6, grp = new THREE.Group();
      const g = geos[type], e = edges[type];
      if (type === 0) { grp.add(new THREE.Mesh(g, this.m.glass), new THREE.LineSegments(e, this.m.e1)); }
      else if (type === 1) { grp.add(new THREE.LineSegments(e, this.m.e3)); }
      else if (type === 2) { grp.add(new THREE.Mesh(g, this.m.ring)); }
      else if (type === 3) { grp.add(new THREE.LineSegments(e, this.m.e2)); const inner = new THREE.LineSegments(this.innerEdges, this.m.e1); inner.rotation.set(0.6, 0.6, 0); grp.add(inner); }
      else if (type === 4) { grp.add(new THREE.Mesh(g, this.m.solid), new THREE.LineSegments(e, this.m.e1)); }
      else { grp.add(new THREE.Mesh(g, this.m.glass), new THREE.LineSegments(e, this.m.e3)); }
      const o = { grp, base: 0.45 + r() * 1.0, ax: (r() - 0.5) * 0.8, ay: (r() - 0.5) * 0.8, az: (r() - 0.5) * 0.4, spin: new Spring(8, 3, 1), pulse: new Spring(60, 7, 0), ph: r() * 10, x: 0, y: 0 };
      this.place(o, true);
      this.scene.add(grp); this.objs.push(o);
    }
    // fragments
    this.frag = new THREE.InstancedMesh(new THREE.TetrahedronGeometry(0.13, 0), new THREE.MeshBasicMaterial({ transparent: true, blending: add, depthWrite: false }), FRAG);
    this.frag.frustumCulled = false; this.scene.add(this.frag);
    this.fs = new Float32Array(FRAG * 8); // px py pz vx vy vz life rot
    this.dummy = new THREE.Object3D();
    for (let i = 0; i < FRAG; i++) { this.dummy.scale.setScalar(0); this.dummy.updateMatrix(); this.frag.setMatrixAt(i, this.dummy.matrix); }
    // energy ribbon
    this.ribU = { ...P, uTime: { value: 0 }, uAmp: { value: 1 }, uAlpha: { value: 0.5 } };
    this.rib = new THREE.Mesh(new THREE.PlaneGeometry(1, 1, 300, 8), new THREE.ShaderMaterial({ uniforms: this.ribU, vertexShader: RIB_VS, fragmentShader: RIB_FS, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: add }));
    this.rib.frustumCulled = false; this.scene.add(this.rib);
    this.flow = new Spring(6, 4, 1); this.N = 30;
  }
  place(o, initial) {
    const r = this.r, a = r() * Math.PI * 2, rad = 3.4 + r() * 7.5;
    o.x = Math.cos(a) * rad * Math.max(1, this.aspect * 0.75); o.y = Math.sin(a) * rad * 0.62;
    o.grp.position.set(o.x, o.y, initial ? ZFAR + r() * (ZNEAR - ZFAR) : ZFAR - r() * 6);
    o.grp.rotation.set(r() * 6, r() * 6, r() * 6);
  }
  setQuality(q, mult) {
    this.N = Math.round(15 + 25 * mult);
    this.objs.forEach((o, i) => (o.grp.visible = i < this.N));
  }
  resize(w, h) { super.resize(w, h); this.aspect = w / h; }
  spawnFrom(o, n, strength) {
    const fs = this.fs, r = this.r;
    for (let k = 0, i = 0; i < FRAG && k < n; i++) {
      if (fs[i * 8 + 6] > 0) continue;
      const b = i * 8, p = o.grp.position;
      let vx = r() - 0.5, vy = r() - 0.5, vz = r() - 0.5; const l = Math.hypot(vx, vy, vz) || 1, sp = (2 + r() * 4) * (0.6 + strength);
      fs[b] = p.x; fs[b + 1] = p.y; fs[b + 2] = p.z; fs[b + 3] = (vx / l) * sp; fs[b + 4] = (vy / l) * sp; fs[b + 5] = (vz / l) * sp; fs[b + 6] = 1; fs[b + 7] = r() * 6;
      k++;
    }
  }
  update(s, dt, rdt) {
    const Pm = this.params, P = this.ctx.pal;
    this.t += dt;
    // palette -> built-in materials (cheap copies, palette may be blending)
    this.m.glass.color.copy(P.uC1.value); this.m.glass.emissive.copy(P.uC1.value).multiplyScalar(0.15);
    this.m.solid.color.copy(P.uBg1.value); this.m.solid.emissive.copy(P.uC1.value).multiplyScalar(0.12);
    this.m.ring.color.copy(P.uC2.value); this.m.e1.color.copy(P.uC2.value); this.m.e2.color.copy(P.uHi.value); this.m.e3.color.copy(P.uC3.value);
    this.frag.material.color.copy(P.uHi.value);
    this.amb.color.copy(P.uC1.value); this.pl1.color.copy(P.uC2.value); this.pl2.color.copy(P.uC3.value);
    this.scene.fog.color.copy(P.uBg0.value).lerp(P.uBg1.value, 0.25);

    const hit = this.beatHit(s, 0.3);
    const speed = this.flow.step(1 + s.rms * 2.5 * Pm.intensity, rdt) * 2.2 * Pm.motionAmount;
    if (hit) this.flow.kick(hit * 4 * Pm.intensity);
    let spawned = 0;
    for (let i = 0; i < this.N; i++) {
      const o = this.objs[i], g = o.grp;
      if (hit) { o.spin.kick((2 + Math.random() * 3) * hit); o.pulse.kick(hit * 3); }
      const sp = o.spin.step(1, rdt);
      g.rotation.x += o.ax * dt * sp; g.rotation.y += o.ay * dt * sp; g.rotation.z += o.az * dt * sp;
      g.position.z += dt * speed;
      g.position.x = o.x + Math.sin(this.t * 0.2 + o.ph) * 0.5;
      g.position.y = o.y + Math.cos(this.t * 0.17 + o.ph) * 0.4;
      g.scale.setScalar(o.base * (1 + o.pulse.step(0, rdt) * 0.12 + s.bass * 0.15));
      if (g.position.z > ZNEAR) this.place(o, false);
      if (hit > 0.45 && spawned < 2 && g.position.z > -26 && g.position.z < 2 && Math.random() < 0.6) { this.spawnFrom(o, 14, hit); spawned++; }
    }
    // fragments
    const fs = this.fs, d = this.dummy, damp = Math.exp(-rdt * 1.6);
    for (let i = 0; i < FRAG; i++) {
      const b = i * 8;
      if (fs[b + 6] <= 0) continue;
      fs[b + 6] -= rdt * 0.6;
      fs[b + 3] *= damp; fs[b + 4] *= damp; fs[b + 5] *= damp;
      fs[b] += fs[b + 3] * rdt; fs[b + 1] += fs[b + 4] * rdt; fs[b + 2] += (fs[b + 5] + speed) * rdt;
      fs[b + 7] += rdt * 3;
      d.position.set(fs[b], fs[b + 1], fs[b + 2]); d.rotation.set(fs[b + 7], fs[b + 7] * 0.7, 0);
      d.scale.setScalar(Math.max(0, fs[b + 6]));
      d.updateMatrix(); this.frag.setMatrixAt(i, d.matrix);
    }
    this.frag.instanceMatrix.needsUpdate = true;
    this.ribU.uTime.value = this.t; this.ribU.uAmp.value = 0.6 + s.mid * 1.2; this.ribU.uAlpha.value = (0.35 + s.speechActivity * 0.3 + s.mid * 0.3) * Pm.opacity;
    this.camera.position.x = Math.sin(this.t * 0.06) * 1.0; this.camera.position.y = Math.sin(this.t * 0.045) * 0.6;
    this.camera.lookAt(0, 0, -20);
    this.bg.material.uniforms.uTime.value = this.t;
  }
  stats() { let f = 0; for (let i = 0; i < FRAG; i++) if (this.fs[i * 8 + 6] > 0) f++; return { objects: this.N, particles: f }; }
}
