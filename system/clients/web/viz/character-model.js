import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/+esm";
import { GLTFLoader } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js/+esm";

// options.fileUrl(rel): URL of another file of the same collection entry (a sibling <slug>.anims.glb holding clips)
export async function createCharacterViewer(container, url, options = {}) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`model download returned ${response.status}`);
  const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), "");
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setClearColor(0x16181d);
  renderer.domElement.style.cssText = "width:100%;height:100%;display:block;touch-action:none";
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x405070, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2); sun.position.set(3, 5, 4); scene.add(sun);
  const holder = new THREE.Group();                     // the mixer root: model first, then clip GLBs (bones bind by name)
  holder.add(gltf.scene); scene.add(holder);
  const bounds = new THREE.Box3().setFromObject(gltf.scene);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = Math.max(bounds.getSize(new THREE.Vector3()).length(), 0.1);
  gltf.scene.position.sub(center);
  const camera = new THREE.PerspectiveCamera(40, 1, Math.max(0.001, size / 1000), size * 50);
  camera.position.set(size * 0.55, size * 0.35, size * (options.distance ?? 3));
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.autoRotate = options.autoRotate ?? true; controls.autoRotateSpeed = 1;
  let dead = false, frameId = 0, player = null;
  let paintHandler=null;const paintTextures=new Set(),generatedTextures=new Map(),raycaster=new THREE.Raycaster();
  function paintEvent(event){
    if(!paintHandler||event.button>0||event.type==='pointermove'&&!(event.buttons&1))return;
    const rect=renderer.domElement.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
    const hit=raycaster.intersectObject(gltf.scene,true).find(h=>h.uv);
    if(hit){const material=Array.isArray(hit.object.material)?hit.object.material[hit.face.materialIndex]:hit.object.material;paintHandler({u:hit.uv.x,v:hit.uv.y,material:material?.name,event});}
    event.preventDefault();event.stopImmediatePropagation();
  }
  renderer.domElement.addEventListener('pointerdown',paintEvent,true);renderer.domElement.addEventListener('pointermove',paintEvent,true);
  const clock = new THREE.Clock(), files = new Map();
  const resize = () => {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize); observer.observe(container); resize();
  const getView=()=>({position:camera.position.toArray().map(x=>x/size),target:controls.target.toArray().map(x=>x/size)});
  controls.addEventListener('change',()=>options.onViewChange?.(getView()));
  function frame() { if (dead) return; frameId = requestAnimationFrame(frame); const dt = clock.getDelta(); player?.update(dt); controls.update(); renderer.render(scene, camera); }
  frame();
  // the clips of one GLB of this entry: the model's own, or a sibling clip file loaded once and kept under holder
  async function clipsOf(file) {
    if (!file || file === options.model) return gltf.animations;
    if (!files.has(file)) files.set(file, (async () => {
      if (!options.fileUrl) throw new Error("no clip file URL");
      const r = await fetch(options.fileUrl(file));
      if (!r.ok) throw new Error(`clip file download returned ${r.status}`);
      const g = await new GLTFLoader().parseAsync(await r.arrayBuffer(), "");
      if (dead) return [];
      g.scene.visible = false; holder.add(g.scene);
      return g.animations;
    })());
    return files.get(file);
  }
  return {
    THREE, holder, gltf,
    materials(){const names=new Set();gltf.scene.traverse(o=>{if(o.isMesh)for(const m of [].concat(o.material||[]))if(m.map)names.add(m.name);});return [...names];},
    paint(handler){paintHandler=handler;controls.enabled=!handler;controls.autoRotate=handler?false:(options.autoRotate??true);},
    texture(image,materialName){
      let texture=generatedTextures.get(materialName);
      if(texture){texture.image=image;texture.needsUpdate=true;return;}
      texture=new THREE.CanvasTexture(image);texture.flipY=false;texture.colorSpace=THREE.SRGBColorSpace;paintTextures.add(texture);generatedTextures.set(materialName,texture);
      gltf.scene.traverse(o=>{if(o.isMesh)for(const m of [].concat(o.material||[]))if(m.name===materialName){if(m.map)paintTextures.add(m.map);m.map=texture;m.needsUpdate=true;}});
    },
    getView,
    setView(pose) {
      if(!pose||![pose.position,pose.target].every(a=>Array.isArray(a)&&a.length===3&&a.every(Number.isFinite)))return;
      camera.position.fromArray(pose.position.map(x=>x*size));controls.target.fromArray(pose.target.map(x=>x*size));controls.update();
    },
    snapshot() { renderer.render(scene,camera); return renderer.domElement.toDataURL('image/png'); },
    embedded: gltf.animations.map(a => ({ name: a.name, duration: a.duration })),
    async clip(row) {
      const found = (await clipsOf(row.file)).find(a => a.name === row.name);
      if (!found) throw new Error(`${row.name} is not in ${row.file || "the model"}`);
      return found;
    },
    setPlayer(p) { player = p; },
    dispose() {
      if (dead) return;
      dead = true; cancelAnimationFrame(frameId); observer.disconnect(); controls.dispose(); player?.dispose?.(); player = null;
      paintHandler=null;for(const texture of paintTextures)texture.dispose();paintTextures.clear();generatedTextures.clear();
      gltf.scene.traverse(o => { if (!o.isMesh) return; o.geometry?.dispose();
        for (const material of [].concat(o.material || [])) { for (const value of Object.values(material)) if (value?.isTexture) value.dispose(); material.dispose(); }
      });
      renderer.dispose(); renderer.domElement.remove();
    } };
}
