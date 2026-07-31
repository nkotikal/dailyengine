// Turning one task into one glowing object: a core sphere, an additive halo, a
// completion ring, an optional icon, a text plate, and a preview of its children.

import * as THREE from "three";
import { glowTexture, iconTexture, labelTexture, reticleTexture, sparkTexture } from "./gfx.js";
import { statusColor } from "./themes.js";

const CORE_GEO = new THREE.IcosahedronGeometry(1, 3);
CORE_GEO.userData.shared = true;
const RING_INNER = 1.26;
const RING_OUTER = 1.44;

/** Bigger subtrees get bigger orbs, but sub-linearly so one huge area cannot swamp the view. */
function orbRadius(stats, base = 1) {
  return base * (0.78 + Math.min(1.6, Math.log2(1 + (stats.total || 1)) * 0.34));
}

function haloSprite(color, radius, strength) {
  const mat = new THREE.SpriteMaterial({
    map: glowTexture(),
    color,
    transparent: true,
    opacity: strength,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
  });
  const s = new THREE.Sprite(mat);
  s.scale.setScalar(radius * 6.2);
  s.renderOrder = -1;
  return s;
}

// Label heights are a fraction of the viewport height rather than a world size, so
// text stays the same size on screen however far you dive in or zoom out.
const LABEL_SCREEN = { title: 0.030, count: 0.019, core: 0.042 };

function labelSprite(text, opts) {
  const { texture, aspect } = labelTexture(text, opts);
  const mat = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthWrite: false, depthTest: false,
    opacity: opts.opacity === undefined ? 0.96 : opts.opacity,
  });
  const s = new THREE.Sprite(mat);
  s.scale.set(aspect, 1, 1);
  s.renderOrder = 10;
  s.userData.aspect = aspect;
  s.userData.screen = LABEL_SCREEN[opts.role || "title"];
  return s;
}

const _worldPos = new THREE.Vector3();

/** Re-scale and re-stack a node's labels for the current camera distance. */
function fitLabels(labels, camera, object, radius, boost) {
  if (!labels || !labels.length) return;
  object.getWorldPosition(_worldPos);
  const dist = camera.position.distanceTo(_worldPos);
  // World-space height of the viewport at this distance.
  const span = 2 * dist * Math.tan((camera.fov * Math.PI) / 360);
  let cursor = -radius - 0.3;
  for (let i = 0; i < labels.length; i += 1) {
    const s = labels[i];
    const h = span * s.userData.screen * boost;
    s.scale.set(h * s.userData.aspect, h, 1);
    cursor -= h * 0.55;
    s.position.y = cursor;
    cursor -= h * 0.55;
  }
}

function progressRing(color, pct, radius) {
  const geo = new THREE.RingGeometry(
    radius * RING_INNER, radius * RING_OUTER, 64, 1,
    Math.PI / 2, -Math.max(0.001, pct) * Math.PI * 2,
  );
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0.95, side: THREE.DoubleSide,
    depthWrite: false, blending: THREE.AdditiveBlending,
  });
  return new THREE.Mesh(geo, mat);
}

function trackRing(radius) {
  const geo = new THREE.RingGeometry(radius * RING_INNER, radius * RING_OUTER, 64);
  const mat = new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.09,
    side: THREE.DoubleSide, depthWrite: false,
  });
  return new THREE.Mesh(geo, mat);
}

/** A cheap cloud of dots hinting at the children hiding inside an orb. */
function satellites(count, color, radius) {
  const n = Math.min(count, 14);
  if (!n) return null;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2 + i * 0.4;
    const r = radius * (1.85 + (i % 3) * 0.22);
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = Math.sin(i * 2.1) * radius * 0.5;
    pos[i * 3 + 2] = Math.sin(a) * r;
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    size: radius * 0.42, map: sparkTexture(), color,
    transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  return new THREE.Points(geo, mat);
}

/**
 * Build the object for one task.
 * `stats` is the rollup from data.js; `meta` is the Home Base side-car entry.
 */
export function makeOrb({ node, stats, meta, pal, theme, base = 1, showChildren = true }) {
  const group = new THREE.Group();
  const color = statusColor(pal, stats);
  const radius = orbRadius(stats, base);
  const complete = stats.total > 0 && stats.done >= stats.total;

  const emissive = complete ? 0.3 : (stats.overdue ? 1.35 : 0.6 + stats.pct * 0.35);
  const core = new THREE.Mesh(CORE_GEO, new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(complete ? 0.5 : 0.85),
    emissive: color,
    emissiveIntensity: emissive,
    roughness: 0.42,
    metalness: 0.15,
    transparent: true,
    opacity: 1,
  }));
  core.scale.setScalar(radius);
  group.add(core);

  const halo = haloSprite(color, radius, complete ? 0.3 : 0.62);
  group.add(halo);

  // Billboarded badges: the ring + icon + text all face the camera each frame.
  const badge = new THREE.Group();
  group.add(badge);

  let ring = null;
  if (!stats.leaf) {
    badge.add(trackRing(radius));
    ring = progressRing(complete ? pal.ok : color, stats.pct, radius);
    badge.add(ring);
  }

  const glyph = meta && meta.icon;
  if (glyph) {
    const tex = iconTexture(glyph);
    if (tex) {
      const icon = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false, depthTest: false, opacity: 0.95,
      }));
      icon.scale.setScalar(radius * 1.05);
      icon.position.set(0, 0, radius * 1.05);
      icon.renderOrder = 11;
      badge.add(icon);
    }
  }

  const labels = [];
  const label = labelSprite(node.text, { strike: !!node.done, role: "title" });
  badge.add(label);
  labels.push(label);

  const childCount = (node.subtasks || []).length;
  if (childCount) {
    const sub = labelSprite(`${stats.done}/${stats.total}`, {
      role: "count", opacity: 0.82, size: 36,
    });
    badge.add(sub);
    labels.push(sub);
  }

  let dots = null;
  if (showChildren && childCount) {
    dots = satellites(childCount, color, radius);
    if (dots) group.add(dots);
  }

  group.userData = {
    id: node.id,
    kind: stats.leaf ? "task" : "group",
    radius,
    color,
    core,
    halo,
    badge,
    ring,
    dots,
    label,
    labels,
    baseEmissive: emissive,
    overdue: stats.overdue,
    dim: false,
    hover: 0,
    targetHover: 0,
  };

  return group;
}

/**
 * Push an orb back when it falls outside the active filter. This only records a
 * multiplier; the scene multiplies dim x fade x the material's authored opacity, so
 * the two effects can never clobber each other's baseline.
 */
export function setDim(orb, dim) {
  const d = orb.userData;
  d.dim = dim;
  // Dimmed still means readable - a filter should recede the rest of the cosmos,
  // not delete it.
  const factor = dim ? 0.5 : 1;
  d.core.material.emissiveIntensity = d.baseEmissive * (dim ? 0.32 : 1);
  orb.traverse((child) => {
    const mats = Array.isArray(child.material) ? child.material : (child.material ? [child.material] : []);
    mats.forEach((m) => { m.userData.dimFactor = factor; });
  });
}

/** Per-frame life: billboarding, hover easing, and the overdue pulse. */
export function tickOrb(orb, t, camera, dt) {
  const d = orb.userData;
  d.badge.quaternion.copy(camera.quaternion);
  d.hover += (d.targetHover - d.hover) * Math.min(1, dt * 9);
  fitLabels(d.labels, camera, orb, d.radius, 1 + d.hover * 0.3);

  const pulse = d.overdue && !d.dim ? 1 + Math.sin(t * 3.4) * 0.09 : 1;
  const scale = pulse * (1 + d.hover * 0.16);
  d.core.scale.setScalar(d.radius * scale);
  d.halo.scale.setScalar(d.radius * 6.2 * (scale + d.hover * 0.22));
  if (!d.dim) {
    d.core.material.emissiveIntensity = d.baseEmissive * (pulse + d.hover * 0.55);
  }
  if (d.dots) d.dots.rotation.y = t * 0.4;
  d.core.rotation.y = t * 0.12;
  d.core.rotation.x = Math.sin(t * 0.2) * 0.15;
}

export function setHover(orb, on) {
  orb.userData.targetHover = on ? 1 : 0;
}

/** The shared selection reticle - one sprite that follows whatever is selected. */
export function makeReticle(pal) {
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: reticleTexture(),
    color: pal.accent,
    transparent: true,
    opacity: 0.9,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
  }));
  sprite.renderOrder = 20;
  sprite.visible = false;
  return sprite;
}

/** The bright body at the middle of a level: the whole cosmos, or the focused task. */
export function makeCore({ pal, theme, label, pct, color }) {
  const group = new THREE.Group();
  const tint = color || pal.accent;
  const r = theme.coreRadius;

  const core = new THREE.Mesh(CORE_GEO, new THREE.MeshStandardMaterial({
    color: tint.clone().multiplyScalar(0.6),
    emissive: tint,
    emissiveIntensity: 0.95 + pct * 0.7,
    roughness: 0.3,
    metalness: 0.1,
  }));
  core.scale.setScalar(r);
  group.add(core);

  const halo = haloSprite(tint, r, 0.7);
  group.add(halo);

  const corona = haloSprite(pal.accent2, r * 1.5, 0.3);
  group.add(corona);

  const badge = new THREE.Group();
  group.add(badge);
  const labels = [];
  if (label) {
    const plate = labelSprite(label, { role: "core", size: 52 });
    badge.add(plate);
    labels.push(plate);
  }

  group.userData = {
    id: "__core__",
    kind: "core",
    radius: r,
    core,
    halo,
    badge,
    labels,
    tick(t, camera) {
      badge.quaternion.copy(camera.quaternion);
      fitLabels(labels, camera, group, r, 1);
      const p = 1 + Math.sin(t * 0.9) * 0.035;
      core.scale.setScalar(r * p);
      halo.scale.setScalar(r * 6.2 * p);
      corona.scale.setScalar(r * 1.5 * 6.2 * (1 + Math.sin(t * 0.55 + 1) * 0.06));
      core.rotation.y = t * 0.06;
    },
  };
  return group;
}

/** A glowing tether from the centre to a child (Constellation scene). */
export function makeLink(from, to, color) {
  const geo = new THREE.BufferGeometry().setFromPoints([from, to]);
  const mat = new THREE.LineBasicMaterial({
    color, transparent: true, opacity: 0.22, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  return new THREE.Line(geo, mat);
}

/** The faint ellipse a level of orbs travels along (Orbital scene). */
export function makeOrbitRing(radius, color) {
  const pts = [];
  for (let i = 0; i <= 128; i += 1) {
    const a = (i / 128) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const mat = new THREE.LineBasicMaterial({
    color, transparent: true, opacity: 0.13, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  return new THREE.Line(geo, mat);
}
