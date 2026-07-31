// The WebGL half of Home Base.
//
// Only one level of the task tree is instantiated at a time: the focused node sits at
// the origin and its direct children orbit it, each hinting at its own children with a
// few satellite dots. Diving rebuilds around the new focus, so a thousand tasks never
// means a thousand meshes.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

import * as data from "./data.js";
import { disposeTextures, disposeTree } from "./gfx.js";
import { makeCore, makeLink, makeOrb, makeOrbitRing, makeReticle, setDim, setHover, tickOrb } from "./nodes.js";
import { qualityOf, readPalette, sceneOf, statusColor } from "./themes.js";

const EASE = (k) => 1 - Math.pow(1 - k, 3);

export function createScene(mount, hooks = {}) {
  const state = {
    focusId: null,
    filter: { kind: "week", day: null },
    themeId: "space",
    quality: "high",
    selectedId: null,
    hoverId: null,
    running: false,
    disposed: false,
  };

  let pal = readPalette();
  let theme = sceneOf(state.themeId);
  let q = qualityOf(state.quality);

  // --- renderer -------------------------------------------------------------
  const renderer = new THREE.WebGLRenderer({
    antialias: true, alpha: true, powerPreference: "high-performance",
  });
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  // Deliberately under 1: bloom stacks on top, and blown-out orbs all read white,
  // which would throw away the priority colour coding.
  renderer.toneMappingExposure = 0.82;
  mount.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(52, 1, 0.1, 2000);
  camera.position.set(0, 16, 46);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.rotateSpeed = 0.55;
  controls.zoomSpeed = 0.8;
  controls.panSpeed = 0.5;
  controls.minDistance = 6;
  controls.maxDistance = 220;
  controls.enablePan = false;

  const ambient = new THREE.AmbientLight(0xffffff, theme.ambient);
  scene.add(ambient);
  const keyLight = new THREE.PointLight(pal.accent.getHex(), 240, 400, 2);
  keyLight.position.set(0, 6, 0);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(pal.accent2.getHex(), 0.65);
  rimLight.position.set(-30, 24, 18);
  scene.add(rimLight);

  let composer = null;
  let bloom = null;
  let renderPass = null;

  function buildComposer() {
    if (composer) { composer.dispose(); composer = null; bloom = null; renderPass = null; }
    if (!q.bloom) return;
    composer = new EffectComposer(renderer);
    renderPass = new RenderPass(scene, camera);
    composer.addPass(renderPass);
    bloom = new UnrealBloomPass(
      new THREE.Vector2(1, 1), theme.bloom.strength, theme.bloom.radius, theme.bloom.threshold,
    );
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    sizeToMount();
  }

  // --- level ----------------------------------------------------------------
  let backdrop = null;
  let level = null;           // { group, core, orbit, orbs: Map<id, Object3D> }
  const reticle = makeReticle(pal);
  reticle.renderOrder = 30;
  scene.add(reticle);

  let fade = { k: 1, from: 1, to: 1, t: 0, dur: 0.45 };
  let camTween = null;

  function buildBackdrop() {
    if (backdrop) { disposeTree(backdrop.group); backdrop = null; }
    backdrop = theme.build(pal, q);
    scene.add(backdrop.group);
  }

  /**
   * Final opacity is always authored x dim x fade, recomputed from scratch, so a
   * transition can never bake a temporary value in as the new baseline.
   */
  function applyFade(root, k) {
    root.traverse((c) => {
      const mats = Array.isArray(c.material) ? c.material : (c.material ? [c.material] : []);
      mats.forEach((m) => {
        if (m.userData.authored === undefined) m.userData.authored = m.opacity;
        const dim = m.userData.dimFactor === undefined ? 1 : m.userData.dimFactor;
        m.transparent = true;
        m.opacity = m.userData.authored * dim * k;
      });
    });
  }

  function childrenOf(id) {
    if (!id) return data.store.tasks;
    const node = data.nodeById(id);
    return node ? data.kids(node) : data.store.tasks;
  }

  function overallColor() {
    const p = data.progress(state.filter);
    if (p.total && p.done >= p.total) return pal.ok;
    return pal.accent;
  }

  /**
   * Rebuild the visible level.
   * `direction` is +1 diving in, -1 backing out, 0 staying put; `reframe` moves the
   * camera to a comfortable distance and `fadeIn` plays the arrival fade. A plain
   * data refresh (a checkbox toggle, say) uses neither, so nothing flickers.
   */
  function buildLevel(direction = 0, { reframe = true, fadeIn = true } = {}) {
    if (level) { disposeTree(level.group); level = null; }

    const group = new THREE.Group();
    const focusNode = state.focusId ? data.nodeById(state.focusId) : null;
    const kids = childrenOf(state.focusId);
    const orbs = new Map();

    const focusStats = focusNode ? data.statsOf(focusNode.id) : null;
    const prog = data.progress(state.filter);
    const core = makeCore({
      pal,
      theme,
      label: focusNode ? focusNode.text : "HOME BASE",
      pct: focusStats ? focusStats.pct : prog.pct,
      color: focusNode ? statusColor(pal, focusStats) : overallColor(),
    });
    group.add(core);

    const spread = 1;
    const layout = theme.layout(kids.length, spread);
    const orbit = new THREE.Group();
    group.add(orbit);

    kids.forEach((node, i) => {
      const stats = data.statsOf(node.id);
      const orb = makeOrb({
        node, stats, meta: data.metaOf(node.id), pal, theme,
        base: 1, showChildren: true,
      });
      const p = layout.place(i, kids.length, layout.radius);
      orb.position.copy(p);
      orb.userData.base = p.clone();

      // A generous invisible sphere so small orbs are still easy to click.
      const hit = new THREE.Mesh(
        new THREE.SphereGeometry(orb.userData.radius * 1.9, 12, 8),
        new THREE.MeshBasicMaterial({ visible: false }),
      );
      hit.userData.orbId = node.id;
      orb.add(hit);
      orb.userData.hit = hit;

      orbit.add(orb);
      orbs.set(node.id, orb);
    });

    if (theme.showOrbits && kids.length) {
      group.add(makeOrbitRing(layout.radius, pal.accent));
    }
    if (theme.showLinks) {
      kids.forEach((node) => {
        const orb = orbs.get(node.id);
        const link = makeLink(new THREE.Vector3(0, 0, 0), orb.userData.base,
          statusColor(pal, data.statsOf(node.id)));
        group.add(link);
      });
    }

    scene.add(group);
    level = { group, core, orbit, orbs, radius: layout.radius };
    applyDim();

    if (fadeIn) {
      // Fade the new level up, and fly the camera in from too-close (diving in) or
      // too-far (backing out) so the change of altitude is legible.
      fade = { k: 0, from: 0, to: 1, t: 0, dur: 0.42 };
    } else {
      fade = { k: 1, from: 1, to: 1, t: 0, dur: 0.42 };
    }
    applyFade(group, fade.k);
    if (reframe) {
      const dist = frameDistance();
      const start = direction > 0 ? 0.5 : (direction < 0 ? 1.7 : 1);
      const dir = camera.position.clone().normalize();
      if (dir.lengthSq() < 0.001) dir.set(0, 0.35, 1).normalize();
      camera.position.copy(dir.multiplyScalar(dist * start));
      tweenCamera(dist, direction === 0 ? 0.35 : 0.75);
    }
    syncReticle();
  }

  function frameDistance() {
    const r = level ? level.radius : 20;
    const kids = childrenOf(state.focusId).length;
    if (!kids) return 26;
    return Math.max(24, r * 2.15 + 10);
  }

  function tweenCamera(distance, dur) {
    const dir = camera.position.clone();
    if (dir.lengthSq() < 0.0001) dir.set(0, 0.35, 1);
    dir.normalize();
    // Keep a pleasant downward tilt regardless of where the user left the camera.
    const target = dir.multiplyScalar(distance);
    target.y = Math.max(target.y, distance * 0.22);
    target.setLength(distance);
    camTween = { from: camera.position.clone(), to: target, t: 0, dur: Math.max(0.01, dur) };
  }

  // --- filter / selection ---------------------------------------------------

  function applyDim() {
    if (!level) return;
    // If the filter matches nothing here, highlighting nothing is more useful than
    // greying out the whole level.
    let any = false;
    level.orbs.forEach((orb, id) => { if (data.statsOf(id).match) any = true; });
    level.orbs.forEach((orb, id) => {
      setDim(orb, any && !data.statsOf(id).match);
    });
    applyFade(level.group, fade.k);
  }

  function syncReticle() {
    const orb = state.selectedId && level ? level.orbs.get(state.selectedId) : null;
    reticle.visible = !!orb;
    if (orb) {
      reticle.scale.setScalar(orb.userData.radius * 4.6);
      reticle.material.color.copy(pal.accent);
    }
  }

  // --- interaction ----------------------------------------------------------

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let downAt = null;

  function pick(ev) {
    if (!level) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const targets = [];
    level.orbs.forEach((orb) => targets.push(orb.userData.hit));
    const hits = raycaster.intersectObjects(targets, false);
    return hits.length ? hits[0].object.userData.orbId : null;
  }

  function onPointerMove(ev) {
    const id = pick(ev);
    if (id === state.hoverId) return;
    if (state.hoverId && level.orbs.has(state.hoverId)) setHover(level.orbs.get(state.hoverId), false);
    state.hoverId = id;
    if (id) setHover(level.orbs.get(id), true);
    renderer.domElement.style.cursor = id ? "pointer" : "grab";
    if (hooks.onHover) hooks.onHover(id);
  }

  function onPointerDown(ev) {
    downAt = { x: ev.clientX, y: ev.clientY, t: performance.now() };
  }

  function onPointerUp(ev) {
    if (!downAt) return;
    const moved = Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y);
    const quick = performance.now() - downAt.t < 500;
    downAt = null;
    if (moved > 5 || !quick) return; // that was an orbit drag, not a click
    const id = pick(ev);
    select(id);
  }

  function onDoubleClick(ev) {
    const id = pick(ev);
    if (id) focus(id);
    else if (state.focusId) ascend();
  }

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  renderer.domElement.addEventListener("pointerdown", onPointerDown);
  renderer.domElement.addEventListener("pointerup", onPointerUp);
  renderer.domElement.addEventListener("dblclick", onDoubleClick);
  renderer.domElement.style.cursor = "grab";

  // --- public actions -------------------------------------------------------

  function select(id) {
    state.selectedId = id || null;
    syncReticle();
    if (hooks.onSelect) hooks.onSelect(state.selectedId);
  }

  function focus(id) {
    const node = id ? data.nodeById(id) : null;
    state.focusId = node ? id : null;
    state.selectedId = node ? id : null;
    buildLevel(1);
    if (hooks.onFocus) hooks.onFocus(state.focusId);
    if (hooks.onSelect) hooks.onSelect(state.selectedId);
  }

  function ascend() {
    if (!state.focusId) return;
    const chain = data.chainOf(state.focusId);
    const parent = chain.length >= 2 ? chain[chain.length - 2] : null;
    const wasFocused = state.focusId;
    state.focusId = parent ? parent.id : null;
    state.selectedId = wasFocused;
    buildLevel(-1);
    if (hooks.onFocus) hooks.onFocus(state.focusId);
    if (hooks.onSelect) hooks.onSelect(state.selectedId);
  }

  function refreshData(opts) {
    // The forest changed under us; keep the focus and selection if they survived.
    if (state.focusId && !data.nodeById(state.focusId)) state.focusId = null;
    if (state.selectedId && !data.nodeById(state.selectedId)) state.selectedId = null;
    buildLevel(0, { reframe: false, fadeIn: false, ...(opts || {}) });
  }

  function setFilter(filter) {
    state.filter = filter;
    applyDim();
  }

  function setTheme(id) {
    if (id === state.themeId) return;
    state.themeId = id;
    theme = sceneOf(id);
    ambient.intensity = theme.ambient;
    buildBackdrop();
    buildComposer();
    buildLevel(0);
  }

  function setQuality(name) {
    if (name === state.quality) return;
    state.quality = name;
    q = qualityOf(name);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, q.pixelRatio));
    buildBackdrop();
    buildComposer();
    sizeToMount();
  }

  function refreshPalette() {
    pal = readPalette();
    keyLight.color.copy(pal.accent);
    rimLight.color.copy(pal.accent2);
    buildBackdrop();
    buildLevel(0);
  }

  // --- loop -----------------------------------------------------------------

  function sizeToMount() {
    const w = Math.max(1, mount.clientWidth);
    const h = Math.max(1, mount.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, q.pixelRatio));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (composer) composer.setSize(w, h);
    if (bloom) bloom.setSize(w, h);
  }

  let raf = 0;
  let lastFrame = 0;
  let elapsed = 0;

  function frame() {
    if (!state.running || state.disposed) return;
    raf = requestAnimationFrame(frame);
    // Own timer rather than THREE.Clock (deprecated), and clamped so pausing the
    // tab for a minute does not jump every animation forward by a minute.
    const now = performance.now() / 1000;
    const dt = lastFrame ? Math.min(0.05, now - lastFrame) : 0.016;
    lastFrame = now;
    elapsed += dt;
    const t = elapsed;

    if (backdrop) backdrop.update(t);

    if (fade.k !== fade.to) {
      fade.t += dt;
      const k = Math.min(1, fade.t / fade.dur);
      fade.k = fade.from + (fade.to - fade.from) * EASE(k);
      if (level) applyFade(level.group, fade.k);
    }

    if (camTween) {
      camTween.t += dt;
      const k = Math.min(1, camTween.t / camTween.dur);
      camera.position.lerpVectors(camTween.from, camTween.to, EASE(k));
      if (k >= 1) camTween = null;
    }

    if (level) {
      theme.animate(level.orbit, t);
      level.core.userData.tick(t, camera);
      level.orbs.forEach((orb) => tickOrb(orb, t, camera, dt));
      if (state.selectedId && level.orbs.has(state.selectedId)) {
        level.orbs.get(state.selectedId).getWorldPosition(reticle.position);
        reticle.material.opacity = 0.55 + Math.sin(t * 2.4) * 0.25;
      } else if (state.selectedId === state.focusId && state.focusId) {
        level.core.getWorldPosition(reticle.position);
        reticle.visible = true;
        reticle.scale.setScalar(theme.coreRadius * 4.2);
      }
    }

    controls.update();
    if (composer) composer.render(dt);
    else renderer.render(scene, camera);
  }

  const ro = new ResizeObserver(() => sizeToMount());
  ro.observe(mount);

  function start() {
    if (state.running || state.disposed) return;
    state.running = true;
    lastFrame = 0;
    sizeToMount();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    state.running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function dispose() {
    state.disposed = true;
    stop();
    ro.disconnect();
    renderer.domElement.removeEventListener("pointermove", onPointerMove);
    renderer.domElement.removeEventListener("pointerdown", onPointerDown);
    renderer.domElement.removeEventListener("pointerup", onPointerUp);
    renderer.domElement.removeEventListener("dblclick", onDoubleClick);
    if (level) disposeTree(level.group);
    if (backdrop) disposeTree(backdrop.group);
    disposeTextures();
    if (composer) composer.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
  }

  // --- boot -----------------------------------------------------------------
  buildBackdrop();
  buildComposer();
  buildLevel(0);

  return {
    state,
    start,
    stop,
    dispose,
    resize: sizeToMount,
    select,
    focus,
    ascend,
    refreshData,
    setFilter,
    setTheme,
    setQuality,
    refreshPalette,
    get focusId() { return state.focusId; },
    get selectedId() { return state.selectedId; },
  };
}
