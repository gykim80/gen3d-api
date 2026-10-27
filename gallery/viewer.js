// 3D 뷰어 — glb 메시 · ply 메시/점군 · Gaussian splat(.ply/.splat) 를 같은 궤도 카메라로 돌려 보고 확대한다
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";
import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";

// 부위 색 — 인접 부위가 구분되도록 색상환을 고르게 나눈다
export const PART_COLORS = ["#e4572e", "#29a8ab", "#f3a712", "#6a4c93", "#76b041", "#1982c4", "#ff595e", "#8ac926",
  "#c86bfa", "#ffca3a"];

export function createViewer(canvas, { thumbnail = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: thumbnail, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotateSpeed = 1.6;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.4));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(2, 3, 2.5);
  scene.add(sun);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new SparkRenderer({ renderer }));

  const root = new THREE.Group();
  scene.add(root);
  const partGroup = new THREE.Group();
  scene.add(partGroup);
  let home = null;
  let wire = false;

  function resize() {
    const w = canvas.clientWidth || canvas.width, h = canvas.clientHeight || canvas.height;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function clear(group) {
    for (const o of [...group.children]) {
      group.remove(o);
      o.traverse?.((c) => { c.geometry?.dispose?.(); [].concat(c.material || []).forEach((m) => m.dispose?.()); });
      o.dispose?.();
    }
  }

  // 물체 크기에 맞춰 카메라를 맞춘다
  function frame(box) {
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    const center = box.getCenter(new THREE.Vector3());
    controls.target.copy(center);
    camera.near = size / 100; camera.far = size * 100;
    camera.position.copy(center).add(new THREE.Vector3(0.55, 0.35, 1).normalize().multiplyScalar(size * 1.15));
    camera.updateProjectionMatrix();
    controls.minDistance = size * 0.05; controls.maxDistance = size * 8;
    home = { pos: camera.position.clone(), target: center.clone() };
    controls.update();
  }

  function plyObject(geom, color) {
    geom.computeBoundingBox();
    if (geom.index) {
      geom.computeVertexNormals();
      const hasColor = !!geom.attributes.color && !color;
      return new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
        color: color || 0xffffff, vertexColors: hasColor, roughness: 0.7, metalness: 0.0, side: THREE.DoubleSide }));
    }
    const s = geom.boundingBox.getSize(new THREE.Vector3()).length();
    return new THREE.Points(geom, new THREE.PointsMaterial({
      size: s / 400, color: color || 0xffffff, vertexColors: !!geom.attributes.color && !color }));
  }

  async function load(url, kind) {
    clear(root); clear(partGroup);
    let obj;
    if (kind === "splat") {
      obj = new SplatMesh({ url });
      await obj.initialized;
      // 스플랫은 OpenCV 좌표계(y 아래) — 뒤집어 세운다
      obj.rotation.x = Math.PI;
      root.add(obj);
      root.updateMatrixWorld(true);
      const b = obj.getBoundingBox(true).clone().applyMatrix4(obj.matrixWorld);
      frame(b);
      return;
    }
    if (url.endsWith(".glb")) {
      obj = (await new GLTFLoader().loadAsync(url)).scene;
    } else {
      obj = plyObject(await new PLYLoader().loadAsync(url));
    }
    root.add(obj);
    applyWire();
    frame(new THREE.Box3().setFromObject(root));
  }

  // PartLLM 부위 점군을 색으로 겹쳐 본다
  async function loadParts(parts) {
    clear(partGroup);
    await Promise.all(parts.map(async (p, i) => {
      const o = plyObject(await new PLYLoader().loadAsync(p.url), new THREE.Color(PART_COLORS[i % PART_COLORS.length]));
      o.userData.file = p.file;
      partGroup.add(o);
    }));
  }

  function setPartVisible(file, v) {
    partGroup.children.forEach((o) => { if (o.userData.file === file) o.visible = v; });
  }

  function applyWire() {
    root.traverse((c) => { if (c.isMesh) [].concat(c.material).forEach((m) => { m.wireframe = wire; }); });
  }

  let raf = 0;
  function loop() {
    raf = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  }

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  return {
    load, loadParts, setPartVisible, renderer, scene, camera, controls,
    start() { if (!raf) loop(); },
    stop() { cancelAnimationFrame(raf); raf = 0; },
    renderOnce() { controls.update(); renderer.render(scene, camera); },
    showMesh(v) { root.visible = v; },
    setAutoRotate(v) { controls.autoRotate = v; },
    setWire(v) { wire = v; applyWire(); },
    setBackground(c) { scene.background = c ? new THREE.Color(c) : null; },
    reset() { if (home) { camera.position.copy(home.pos); controls.target.copy(home.target); controls.update(); } },
    zoom(f) { // f<1 확대 · f>1 축소
      const d = camera.position.clone().sub(controls.target).multiplyScalar(f);
      const len = THREE.MathUtils.clamp(d.length(), controls.minDistance, controls.maxDistance);
      camera.position.copy(controls.target).add(d.setLength(len));
    },
    dispose() { this.stop(); ro.disconnect(); clear(root); clear(partGroup); renderer.dispose(); },
  };
}

// three/addons 의 RoomEnvironment 를 따로 받지 않으려고 간단한 실내 반사 환경을 직접 만든다
class RoomEnvironment extends THREE.Scene {
  constructor() {
    super();
    const box = new THREE.BoxGeometry();
    const room = new THREE.Mesh(box, new THREE.MeshStandardMaterial({ side: THREE.BackSide, color: 0x888888 }));
    room.scale.set(10, 6, 10);
    this.add(room);
    const lightMat = (i) => new THREE.MeshBasicMaterial({ color: new THREE.Color(i, i, i) });
    [[0, 2.9, 0, 4, 0.1, 4, 6], [-4.9, 1, 0, 0.1, 2, 4, 3], [4.9, 1, 0, 0.1, 2, 4, 3]].forEach(([x, y, z, sx, sy, sz, i]) => {
      const m = new THREE.Mesh(box, lightMat(i));
      m.position.set(x, y, z); m.scale.set(sx, sy, sz);
      this.add(m);
    });
  }
}
