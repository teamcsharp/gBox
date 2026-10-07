// Examine in 3D: three.js viewer for a gbox scene_capture .glb (one node per draw call, "scene" + "hud" layers,
// "game_camera" = the game's own camera at the origin looking down -z).
//   const ex = await createExaminer(container, { onPick(info) {} });
//   await ex.load(url); ex.setHud(on); ex.setWireframe(on); ex.gameView(); ex.setDepth(k); ex.dispose();
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/+esm";
import { GLTFLoader } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js/+esm";

const FACTOR = {
  Zero: THREE.ZeroFactor, One: THREE.OneFactor, SrcCol: THREE.SrcColorFactor, InvSrcCol: THREE.OneMinusSrcColorFactor,
  DstCol: THREE.DstColorFactor, InvDstCol: THREE.OneMinusDstColorFactor, SrcAlpha: THREE.SrcAlphaFactor,
  InvSrcAlpha: THREE.OneMinusSrcAlphaFactor, DstAlpha: THREE.DstAlphaFactor, InvDstAlpha: THREE.OneMinusDstAlphaFactor,
  SrcAlphaSat: THREE.SrcAlphaSaturateFactor,
  Src1Col: THREE.SrcColorFactor, InvSrc1Col: THREE.OneMinusSrcColorFactor,   // dual-source: closest single-source factor
  Src1Alpha: THREE.SrcAlphaFactor, InvSrc1Alpha: THREE.OneMinusSrcAlphaFactor,
};

export async function createExaminer(container, opts = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.setClearColor(0x16181d, 1);
  const canvas = renderer.domElement;
  canvas.style.cssText = "width:100%;height:100%;display:block;outline:none;touch-action:none";
  canvas.tabIndex = 0;
  container.append(canvas);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1e6);
  scene.add(camera);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.12; controls.screenSpacePanning = true;
  const state = { root: null, sceneNode: null, hudNode: null, home: null, picked: null, wire: false, hud: false, depth: 1, raf: 0, dead: false };
  const hl = new THREE.Group(); scene.add(hl);

  function resize() {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(container); resize();
  function loop() { if (state.dead) return; state.raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); }
  loop();

  function clear() {
    if (!state.root) return;
    if (state.hudNode) camera.remove(state.hudNode);
    scene.remove(state.root);
    state.root.traverse(o => { if (o.isMesh) { o.geometry.dispose(); [].concat(o.material).forEach(m => { m.map?.dispose(); m.dispose(); }); } });
    if (state.hudNode) state.hudNode.traverse(o => { if (o.isMesh) { o.geometry.dispose(); [].concat(o.material).forEach(m => { m.map?.dispose(); m.dispose(); }); } });
    state.root = state.sceneNode = state.hudNode = null; select(null);
  }

  async function load(url) {
    const gltf = await new GLTFLoader().loadAsync(url);
    clear();
    const root = gltf.scene;
    state.root = root;
    state.sceneNode = root.getObjectByName("scene") || root;
    state.hudNode = root.getObjectByName("hud");
    root.traverse(o => {
      if (!o.isMesh) return;
      o.renderOrder = o.userData.draw || 0;           // the game's draw order (decals, glass and fog passes rely on it)
      [].concat(o.material).forEach(m => {
        if (m.map) { m.map.magFilter = THREE.NearestFilter; m.map.minFilter = THREE.LinearMipmapLinearFilter; m.map.anisotropy = 4; }
        m.side = THREE.DoubleSide;
        const b = m.userData && m.userData.blend;     // the game's own blend factors -> the same blend in WebGL
        if (m.userData && m.userData.zwrite != null) m.depthWrite = !!m.userData.zwrite;
        if (b && FACTOR[b[0]] !== undefined && FACTOR[b[1]] !== undefined) {
          m.blending = THREE.CustomBlending; m.blendSrc = FACTOR[b[0]]; m.blendDst = FACTOR[b[1]];
          m.blendEquation = { Subtract: THREE.SubtractEquation, ReversedSubtract: THREE.ReverseSubtractEquation, Minimum: THREE.MinEquation, Maximum: THREE.MaxEquation }[b[2]] ?? THREE.AddEquation;
          m.depthWrite = m.userData.zwrite === true; m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -2;
        }
      });
    });
    scene.add(root);
    if (state.hudNode) {                          // HUD: screen-facing overlay, rides with the camera
      state.hudNode.removeFromParent(); camera.add(state.hudNode);
      state.hudNode.traverse(o => { if (o.isMesh) { o.renderOrder = 1000 + (o.userData.draw || 0); [].concat(o.material).forEach(m => { m.depthTest = false; m.transparent = true; }); } });
    }
    const gc = gltf.cameras && gltf.cameras[0];
    const ex = (gltf.parser.json.extras) || {};
    state.info = ex;
    // orbit pivot: median depth of the scene's draws (vertex-weighted), straight ahead of the game camera
    const ds = [];
    state.sceneNode.traverse(o => { if (o.isMesh && o.userData.depth) { const [a, b] = o.userData.depth; if (b > 0) ds.push([(Math.max(a, 0) + b) / 2, o.userData.vertices || 1]); } });
    ds.sort((a, b) => a[0] - b[0]);
    let tot = ds.reduce((s, d) => s + d[1], 0), acc = 0, med = ex.near ? ex.near * 10 : 10;
    for (const d of ds) { acc += d[1]; if (acc >= tot / 2) { med = d[0]; break; } }
    root.updateMatrixWorld(true);                     // pivot: whatever the game camera looks at in the middle of the screen
    const hit = new THREE.Raycaster(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -1)).intersectObject(state.sceneNode, true)
      .find(h => h.object.isMesh && h.distance > 0 && !(h.object.material.blending === THREE.CustomBlending));
    if (hit && hit.distance < med * 4) med = hit.distance;
    const near = Math.max(1e-4, (ex.near || med / 100) * 0.2), far = Math.max(med * 50, (ex.far || med * 10) * 4);
    camera.near = near; camera.far = far;
    state.home = { fov: gc ? gc.fov : 50, target: new THREE.Vector3(0, 0, -med), med };
    setWireframe(state.wire); setHud(state.hud); setDepth(state.depth);
    gameView();
    return { draws: ds.length, pivot: med };
  }

  function gameView() {
    if (!state.home) return;
    camera.fov = state.home.fov; camera.position.set(0, 0, 0); camera.up.set(0, 1, 0);
    controls.target.copy(state.home.target); camera.lookAt(controls.target); camera.updateProjectionMatrix(); controls.update();
  }
  function orbitView(yawDeg, pitchDeg) {           // same pivot, seen from another side (for screenshots / quick looks)
    if (!state.home) return;
    const t = state.home.target, r = state.home.med, a = THREE.MathUtils.degToRad(yawDeg), b = THREE.MathUtils.degToRad(pitchDeg);
    camera.position.set(t.x + r * Math.sin(a) * Math.cos(b), t.y + r * Math.sin(b), t.z + r * Math.cos(a) * Math.cos(b));
    controls.target.copy(t); camera.lookAt(t); controls.update();
  }
  function setHud(on) { state.hud = !!on; if (state.hudNode) state.hudNode.visible = state.hud; }
  function setWireframe(on) {
    state.wire = !!on;
    state.root?.traverse(o => { if (o.isMesh) [].concat(o.material).forEach(m => { m.wireframe = state.wire; }); });
  }
  function setDepth(k) { state.depth = k; if (state.sceneNode) { state.sceneNode.scale.z = k; state.sceneNode.updateMatrixWorld(true); } }
  function setBackground(hex) { renderer.setClearColor(hex, 1); }

  function select(mesh) {
    hl.clear();
    state.picked = mesh;
    if (!mesh) { opts.onPick && opts.onPick(null); return; }
    const w = new THREE.Mesh(mesh.geometry, new THREE.MeshBasicMaterial({ color: 0xffd400, wireframe: true, depthTest: false, transparent: true, opacity: 0.85 }));
    w.matrixAutoUpdate = false; w.matrix.copy(mesh.matrixWorld); w.renderOrder = 2000; hl.add(w);
    const box = new THREE.Box3Helper(new THREE.Box3().setFromObject(mesh), 0xffd400); box.renderOrder = 2001; box.material.depthTest = false; hl.add(box);
    const m = [].concat(mesh.material)[0];
    opts.onPick && opts.onPick({ ...mesh.userData, name: mesh.name, image: m?.map?.image || null });
  }
  // click (not drag) picks the draw call under the cursor
  let down = null;
  canvas.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !state.root) return;
    const r = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, camera);
    const targets = [state.sceneNode, ...(state.hud && state.hudNode ? [state.hudNode] : [])];
    const hit = rc.intersectObjects(targets, true).find(h => h.object.isMesh && h.object.visible);
    select(hit ? hit.object : null);
  });
  canvas.addEventListener("dblclick", () => { if (state.picked) { const c = new THREE.Box3().setFromObject(state.picked).getCenter(new THREE.Vector3()); controls.target.copy(c); } });

  return {
    load, gameView, orbitView, setHud, setWireframe, setDepth, setBackground, select,
    attach(el) { if (canvas.parentNode !== el) { el.append(canvas); ro.disconnect(); container = el; ro.observe(el); resize(); } },
    snapshot() { renderer.render(scene, camera); return canvas.toDataURL("image/png"); },
    get loaded() { return !!state.root; },
    dispose() { state.dead = true; cancelAnimationFrame(state.raf); ro.disconnect(); clear(); controls.dispose(); renderer.dispose(); canvas.remove(); },
  };
}
