// Two independent theme axes:
//   1. COLOR comes from the dashboard's CSS custom properties, so all 12 existing
//      color themes (Neon, Ultraviolet, Daylight...) restyle the cosmos for free.
//   2. SCENE decides the geometry and atmosphere. Adding one means adding an entry
//      to SCENES below - nothing else in the app needs to know about it.

import * as THREE from "three";
import { sparkTexture } from "./gfx.js";

// --- color bridge -----------------------------------------------------------

const FALLBACK = {
  accent: "#7c9bff", accent2: "#c08cff", ok: "#5fe6b4",
  warn: "#ffd479", danger: "#ff8f9c", text: "#f3f5fb",
  blob1: "#6b7bff", blob2: "#c569ff", blob3: "#38e8c8", blob4: "#ff7eb6",
};

const VARS = {
  accent: "--accent", accent2: "--accent-2", ok: "--ok",
  warn: "--warn", danger: "--danger", text: "--text",
  blob1: "--blob-1", blob2: "--blob-2", blob3: "--blob-3", blob4: "--blob-4",
};

function readColor(cs, name, fallback) {
  const raw = (cs.getPropertyValue(name) || "").trim();
  const c = new THREE.Color();
  try {
    c.setStyle(raw || fallback);
  } catch (e) {
    c.setStyle(fallback);
  }
  return c;
}

/** Snapshot the current CSS theme as THREE colors. */
export function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  const pal = {};
  Object.keys(VARS).forEach((k) => { pal[k] = readColor(cs, VARS[k], FALLBACK[k]); });
  pal.blobs = [pal.blob1, pal.blob2, pal.blob3, pal.blob4];
  pal.light = document.documentElement.getAttribute("data-theme") === "daylight";
  return pal;
}

/** Priority drives an orb's hue; overdue always wins. */
export function statusColor(pal, stats) {
  if (stats.overdue) return pal.danger;
  if (stats.total && stats.done >= stats.total) return pal.ok;
  switch (stats.priority) {
    case "critical": return pal.danger;
    case "high": return pal.warn;
    case "low": return pal.blob3;
    default: return pal.accent;
  }
}

// --- quality tiers ----------------------------------------------------------

export const QUALITY = {
  high: { stars: 2600, dust: 700, bloom: true, pixelRatio: 2, nebula: true },
  balanced: { stars: 1500, dust: 300, bloom: true, pixelRatio: 1.5, nebula: true },
  low: { stars: 700, dust: 0, bloom: false, pixelRatio: 1, nebula: false },
};

export function qualityOf(name) {
  return QUALITY[name] || QUALITY.high;
}

// --- shared backdrop pieces -------------------------------------------------

function starfield(pal, count, radius) {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const size = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    // Even-ish shell distribution so stars never clump at the poles.
    const u = Math.random() * 2 - 1;
    const theta = Math.random() * Math.PI * 2;
    const r = radius * (0.55 + Math.random() * 0.45);
    const s = Math.sqrt(1 - u * u);
    pos[i * 3] = r * s * Math.cos(theta);
    pos[i * 3 + 1] = r * u * 0.75;
    pos[i * 3 + 2] = r * s * Math.sin(theta);
    const tint = pal.blobs[i % pal.blobs.length];
    const mix = 0.55 + Math.random() * 0.45;
    col[i * 3] = 1 - (1 - tint.r) * mix;
    col[i * 3 + 1] = 1 - (1 - tint.g) * mix;
    col[i * 3 + 2] = 1 - (1 - tint.b) * mix;
    size[i] = 1.1 + Math.random() * 3.4;
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("aScale", new THREE.BufferAttribute(size, 1));

  const mat = new THREE.PointsMaterial({
    size: 2.6,
    map: sparkTexture(),
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });
  // Twinkle: nudge opacity per frame rather than rebuilding the buffer.
  const points = new THREE.Points(geo, mat);
  points.frustumCulled = false;
  points.userData.twinkle = (t) => { mat.opacity = 0.72 + Math.sin(t * 0.7) * 0.08; };
  return points;
}

function dustCloud(pal, count, radius) {
  if (!count) return null;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    pos[i * 3] = (Math.random() - 0.5) * radius;
    pos[i * 3 + 1] = (Math.random() - 0.5) * radius * 0.6;
    pos[i * 3 + 2] = (Math.random() - 0.5) * radius;
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    size: 0.42,
    map: sparkTexture(),
    color: pal.accent,
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  return pts;
}

const NEBULA_VERT = `
  varying vec3 vPos;
  void main() {
    vPos = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const NEBULA_FRAG = `
  varying vec3 vPos;
  uniform float uTime;
  uniform float uOpacity;
  uniform vec3 uA;
  uniform vec3 uB;
  uniform vec3 uC;

  float hash(vec3 p) {
    return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453123);
  }
  float noise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
          mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
          mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
  }
  float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; }
    return v;
  }

  void main() {
    vec3 dir = normalize(vPos);
    float t = uTime * 0.012;
    float n1 = fbm(dir * 2.1 + vec3(t, t * 0.6, -t * 0.4));
    float n2 = fbm(dir * 4.8 - vec3(t * 0.5, t * 0.9, t * 0.3));
    float density = smoothstep(0.34, 0.92, n1 * 0.75 + n2 * 0.4);
    vec3 col = mix(uA, uB, clamp(n2 * 1.4, 0.0, 1.0));
    col = mix(col, uC, smoothstep(0.55, 1.0, n1));
    float band = 1.0 - abs(dir.y) * 0.65;
    float alpha = density * uOpacity * band;
    gl_FragColor = vec4(col * alpha, alpha);
  }
`;

function nebula(pal, radius, opacity) {
  const uniforms = {
    uTime: { value: 0 },
    uOpacity: { value: opacity },
    uA: { value: pal.blobs[0].clone() },
    uB: { value: pal.blobs[1].clone() },
    uC: { value: pal.blobs[2].clone() },
  };
  const mat = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: NEBULA_VERT,
    fragmentShader: NEBULA_FRAG,
    side: THREE.BackSide,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(radius, 3), mat);
  mesh.frustumCulled = false;
  mesh.userData.uniforms = uniforms;
  return mesh;
}

// --- layouts ----------------------------------------------------------------

function ringLayout(count, spread) {
  // Wider rings for busier levels, but never so wide that labels collide.
  const radius = Math.max(9, Math.min(34, 7 + count * 1.55)) * spread;
  return { radius };
}

function fibonacciSphere(i, count, radius) {
  const k = count <= 1 ? 0.5 : i / (count - 1);
  const y = 1 - k * 2;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const phi = i * Math.PI * (3 - Math.sqrt(5));
  return new THREE.Vector3(Math.cos(phi) * r * radius, y * radius * 0.78, Math.sin(phi) * r * radius);
}

// --- the scenes -------------------------------------------------------------

export const SCENES = {
  space: {
    id: "space",
    label: "Orbital",
    bloom: { strength: 0.55, radius: 0.72, threshold: 0.52 },
    ambient: 0.55,
    showOrbits: true,
    showLinks: false,
    coreRadius: 2.6,
    spin: 0.035,

    build(pal, q) {
      const group = new THREE.Group();
      const stars = starfield(pal, q.stars, 320);
      group.add(stars);
      const neb = q.nebula ? nebula(pal, 260, pal.light ? 0.16 : 0.42) : null;
      if (neb) group.add(neb);
      const dust = dustCloud(pal, q.dust, 90);
      if (dust) group.add(dust);
      return {
        group,
        update(t) {
          stars.rotation.y = t * 0.006;
          if (stars.userData.twinkle) stars.userData.twinkle(t);
          if (neb) {
            neb.userData.uniforms.uTime.value = t;
            neb.rotation.y = -t * 0.004;
          }
          if (dust) {
            dust.rotation.y = t * 0.02;
            dust.position.y = Math.sin(t * 0.25) * 1.5;
          }
        },
      };
    },

    layout(count, spread) {
      const { radius } = ringLayout(count, spread);
      return {
        radius,
        place(i) {
          const angle = count ? (i / count) * Math.PI * 2 : 0;
          // Golden-ratio wobble keeps orbs off a perfect circle so depth reads.
          const wob = Math.sin(i * 2.399) * radius * 0.09;
          return new THREE.Vector3(
            Math.cos(angle) * (radius + wob),
            Math.sin(i * 1.618) * radius * 0.11,
            Math.sin(angle) * (radius + wob),
          );
        },
      };
    },

    animate(orbit, t) {
      orbit.rotation.y = t * this.spin;
      orbit.children.forEach((child, i) => {
        if (!child.userData.base) return;
        child.position.y = child.userData.base.y + Math.sin(t * 0.6 + i * 1.7) * 0.32;
        // Counter-rotate so labels keep facing out as the ring turns.
        child.rotation.y = -orbit.rotation.y;
      });
    },
  },

  constellation: {
    id: "constellation",
    label: "Constellation",
    bloom: { strength: 0.8, radius: 0.85, threshold: 0.38 },
    ambient: 0.35,
    showOrbits: false,
    showLinks: true,
    coreRadius: 2.0,
    spin: 0.012,

    build(pal, q) {
      const group = new THREE.Group();
      const stars = starfield(pal, Math.round(q.stars * 0.55), 340);
      group.add(stars);
      const haze = q.nebula ? nebula(pal, 300, pal.light ? 0.1 : 0.2) : null;
      if (haze) group.add(haze);
      // A slow field of drifting synapses rather than a nebula bed.
      const motes = dustCloud(pal, Math.round(q.dust * 1.4), 130);
      if (motes) group.add(motes);
      return {
        group,
        update(t) {
          stars.rotation.y = -t * 0.004;
          if (stars.userData.twinkle) stars.userData.twinkle(t);
          if (haze) haze.userData.uniforms.uTime.value = t * 0.6;
          if (motes) {
            motes.rotation.y = -t * 0.014;
            motes.rotation.x = Math.sin(t * 0.1) * 0.08;
          }
        },
      };
    },

    layout(count, spread) {
      // Wider than the orbital ring: a sphere packs nodes closer together on screen.
      const radius = Math.max(11, Math.min(36, 9 + count * 1.7)) * spread;
      return {
        radius,
        place(i) { return fibonacciSphere(i, count, radius); },
      };
    },

    animate(orbit, t) {
      orbit.rotation.y = t * this.spin;
      orbit.children.forEach((child, i) => {
        const base = child.userData.base;
        if (!base) return;
        child.position.set(
          base.x + Math.sin(t * 0.4 + i * 0.9) * 0.4,
          base.y + Math.cos(t * 0.33 + i * 1.3) * 0.45,
          base.z + Math.sin(t * 0.29 + i * 2.1) * 0.4,
        );
        child.rotation.y = -orbit.rotation.y;
      });
    },
  },
};

export function sceneOf(id) {
  return SCENES[id] || SCENES.space;
}
