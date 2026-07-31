// Canvas-generated textures for Home Base. Everything is drawn in white so the
// materials can tint it per theme, and every texture is cached and reused - a few
// hundred task sprites must not mean a few hundred canvases.

import * as THREE from "three";

const CACHE = new Map();

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
}

function toTexture(c) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  t.needsUpdate = true;
  return t;
}

function cached(key, make) {
  if (!CACHE.has(key)) CACHE.set(key, make());
  return CACHE.get(key);
}

/** Soft radial falloff - the halo behind every orb. */
export function glowTexture() {
  return cached("glow", () => {
    const s = 256;
    const c = canvas(s, s);
    const g = c.getContext("2d");
    const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    grd.addColorStop(0.0, "rgba(255,255,255,1)");
    grd.addColorStop(0.14, "rgba(255,255,255,0.70)");
    grd.addColorStop(0.34, "rgba(255,255,255,0.22)");
    grd.addColorStop(0.62, "rgba(255,255,255,0.05)");
    grd.addColorStop(1.0, "rgba(255,255,255,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
    return toTexture(c);
  });
}

/** Tiny soft dot for starfields and dust. */
export function sparkTexture() {
  return cached("spark", () => {
    const s = 64;
    const c = canvas(s, s);
    const g = c.getContext("2d");
    const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    grd.addColorStop(0.0, "rgba(255,255,255,1)");
    grd.addColorStop(0.30, "rgba(255,255,255,0.55)");
    grd.addColorStop(1.0, "rgba(255,255,255,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
    return toTexture(c);
  });
}

/** Thin bright annulus - the selection reticle. */
export function reticleTexture() {
  return cached("reticle", () => {
    const s = 256;
    const c = canvas(s, s);
    const g = c.getContext("2d");
    g.strokeStyle = "rgba(255,255,255,0.95)";
    g.lineWidth = 5;
    g.beginPath();
    g.arc(s / 2, s / 2, s / 2 - 14, 0, Math.PI * 2);
    g.stroke();
    g.strokeStyle = "rgba(255,255,255,0.30)";
    g.lineWidth = 14;
    g.beginPath();
    g.arc(s / 2, s / 2, s / 2 - 14, 0, Math.PI * 2);
    g.stroke();
    return toTexture(c);
  });
}

/** An emoji / glyph badge, cached per character. */
export function iconTexture(glyph) {
  const ch = glyph || "";
  if (!ch) return null;
  return cached("icon:" + ch, () => {
    const s = 128;
    const c = canvas(s, s);
    const g = c.getContext("2d");
    g.font = "84px \"Segoe UI Emoji\", \"Apple Color Emoji\", \"Noto Color Emoji\", sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.shadowColor = "rgba(0,0,0,0.65)";
    g.shadowBlur = 10;
    g.fillText(ch, s / 2, s / 2 + 4);
    return toTexture(c);
  });
}

const LABEL_CACHE = new Map();
const LABEL_LIMIT = 400;

/**
 * A text plate. Returns { texture, aspect }. Cached by text+style so re-entering a
 * level does not redraw; the cache is bounded because task names change over time.
 */
export function labelTexture(text, opts = {}) {
  const raw = String(text || "").trim();
  // Long names are the main cause of label collisions in a busy level.
  const clean = (raw.length > 30 ? raw.slice(0, 29).trimEnd() + "\u2026" : raw) || "untitled";
  const strike = !!opts.strike;
  const size = opts.size || 44;
  const key = `${clean}|${strike}|${size}`;
  if (LABEL_CACHE.has(key)) return LABEL_CACHE.get(key);

  // Tight padding so most of the sprite's height is actual glyph - the plates are
  // only ~20px tall on screen and any wasted margin makes them unreadable.
  const pad = 13;
  const probe = canvas(8, 8).getContext("2d");
  const font = `600 ${size}px ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif`;
  probe.font = font;
  const w = Math.ceil(probe.measureText(clean).width) + pad * 2;
  const h = size + pad * 2;
  const c = canvas(w, h);
  const g = c.getContext("2d");
  g.font = font;
  g.textAlign = "center";
  g.textBaseline = "middle";
  // Dark halo first so the text stays readable against bright nebulae.
  g.shadowColor = "rgba(0,0,0,0.95)";
  g.shadowBlur = 14;
  g.fillStyle = "rgba(0,0,0,0.85)";
  g.fillText(clean, w / 2, h / 2);
  g.shadowBlur = 0;
  g.fillStyle = "#ffffff";
  g.fillText(clean, w / 2, h / 2);
  if (strike) {
    g.strokeStyle = "rgba(255,255,255,0.85)";
    g.lineWidth = Math.max(2, size / 16);
    g.beginPath();
    g.moveTo(pad * 0.7, h / 2);
    g.lineTo(w - pad * 0.7, h / 2);
    g.stroke();
  }

  const entry = { texture: toTexture(c), aspect: w / h };
  if (LABEL_CACHE.size > LABEL_LIMIT) {
    const [oldest] = LABEL_CACHE.keys();
    const dead = LABEL_CACHE.get(oldest);
    if (dead) dead.texture.dispose();
    LABEL_CACHE.delete(oldest);
  }
  LABEL_CACHE.set(key, entry);
  return entry;
}

/** Free every cached texture (called when the tab is torn down). */
export function disposeTextures() {
  CACHE.forEach((t) => t && t.dispose && t.dispose());
  CACHE.clear();
  LABEL_CACHE.forEach((e) => e.texture.dispose());
  LABEL_CACHE.clear();
}

/** Recursively free the geometry/material of anything under `obj`. */
export function disposeTree(obj) {
  if (!obj) return;
  obj.traverse((child) => {
    // Geometries flagged `shared` outlive any single level rebuild.
    if (child.geometry && !child.geometry.userData.shared) child.geometry.dispose();
    const mats = Array.isArray(child.material) ? child.material : [child.material];
    mats.forEach((m) => {
      if (!m) return;
      // Shared cached textures are freed by disposeTextures, not here.
      m.dispose();
    });
  });
  if (obj.parent) obj.parent.remove(obj);
}
