import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/+esm";
import { GLTFLoader } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js/+esm";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js/+esm";

export async function createCharacterViewer(container, url) {
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
  scene.add(gltf.scene);
  const bounds = new THREE.Box3().setFromObject(gltf.scene);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = Math.max(bounds.getSize(new THREE.Vector3()).length(), 0.1);
  gltf.scene.position.sub(center);
  const camera = new THREE.PerspectiveCamera(40, 1, Math.max(0.001, size / 1000), size * 50);
  camera.position.set(size * 0.55, size * 0.35, size * 3);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 1;
  let dead = false, frameId = 0;
  const resize = () => {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize); observer.observe(container); resize();
  function frame() { if (dead) return; frameId = requestAnimationFrame(frame); controls.update(); renderer.render(scene, camera); }
  frame();
  return { dispose() {
    if (dead) return;
    dead = true; cancelAnimationFrame(frameId); observer.disconnect(); controls.dispose();
    gltf.scene.traverse(o => { if (!o.isMesh) return; o.geometry?.dispose();
      for (const material of [].concat(o.material || [])) { for (const value of Object.values(material)) if (value?.isTexture) value.dispose(); material.dispose(); }
    });
    renderer.dispose(); renderer.domElement.remove();
  } };
}
