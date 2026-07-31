// Home Base entry point. Owns the shared `app` object that the scene, the HUD and
// the chat panel all talk through, and exposes window.HomeBase so digest.js can
// start and stop the render loop as the tab comes and goes.

import * as data from "./data.js";
import { createScene } from "./scene.js";
import { initChat, openChat, refreshChat } from "./chat.js";
import { initHUD, renderCrumbs, renderInspector, renderProgress, syncFilterChips, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);

let booted = false;
let booting = null;
let wantsRunning = false;

const app = {
  scene: null,
  filter: { kind: "week", day: null },
  llmReady: false,

  get selectedId() { return app.scene ? app.scene.selectedId : null; },

  /** Fold a server response into the store and repaint. */
  absorb(res, rebuild = true) {
    data.absorb(res, app.filter);
    if (app.scene && rebuild) app.scene.refreshData();
    app.refreshHUD();
    return res;
  },

  refreshHUD() {
    renderProgress(app);
    renderCrumbs(app);
    renderInspector(app);
    refreshChat(app);
  },

  async reload(rebuild = true) {
    await data.loadState(app.filter);
    app.llmReady = data.store.llmReady;
    if (app.scene && rebuild) app.scene.refreshData();
    app.refreshHUD();
  },

  select(id) {
    if (app.scene) app.scene.select(id);
  },

  focus(id) {
    if (app.scene) app.scene.focus(id);
  },

  setFilter(filter) {
    app.filter = filter;
    data.reindex(app.filter);
    syncFilterChips(app);
    if (app.scene) app.scene.setFilter(app.filter);
    renderProgress(app);
    app.savePrefs({ filter: filter.kind === "day" ? "week" : filter.kind });
  },

  async update(id, fields) {
    if (!id) return;
    try {
      app.absorb(await data.req("/api/digest/tasks/update", { id, fields }));
    } catch (e) {
      toast(e.message, true);
    }
  },

  async addChild(parentId, text) {
    if (!parentId || !text) return;
    try {
      app.absorb(await data.req("/api/digest/tasks/subtask/add", { parent_id: parentId, text }));
      toast("Added");
    } catch (e) {
      toast(e.message, true);
    }
  },

  async remove(id, label) {
    if (!id) return;
    if (!confirm(`Delete "${label}" and everything under it?`)) return;
    const wasFocus = app.scene && app.scene.focusId === id;
    try {
      const res = await data.req("/api/digest/tasks/delete", { id });
      if (wasFocus) app.scene.ascend();
      app.absorb(res, !wasFocus);
      toast("Deleted");
    } catch (e) {
      toast(e.message, true);
    }
  },

  async setMeta(id, fields) {
    if (!id) return;
    try {
      const res = await data.req("/api/homebase/meta", { id, fields });
      data.store.meta = res.meta || data.store.meta;
      if (app.scene) app.scene.refreshData();
      app.refreshHUD();
    } catch (e) {
      toast(e.message, true);
    }
  },

  savePrefs(prefs) {
    data.req("/api/homebase/prefs", prefs).catch(() => { /* preferences are cosmetic */ });
  },

  openChat(id) {
    if (!id) return;
    openChat(app, id);
  },
};

// --- boot -------------------------------------------------------------------

function applyPrefs(prefs) {
  const kind = data.FILTERS.includes(prefs.filter) ? prefs.filter : "week";
  app.filter = { kind, day: null };
  syncFilterChips(app);
  $("hb-scene").value = prefs.scene_theme || "space";
  $("hb-quality").value = prefs.quality || "high";
}

function watchColorTheme() {
  const observer = new MutationObserver((records) => {
    if (!app.scene) return;
    if (records.some((r) => r.attributeName === "data-theme")) app.scene.refreshPalette();
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

function fail(message) {
  const overlay = $("hb-loading");
  overlay.classList.remove("gone");
  overlay.textContent = message;
}

async function boot() {
  const overlay = $("hb-loading");
  try {
    await data.loadState(app.filter);
    app.llmReady = data.store.llmReady;
    applyPrefs(data.store.prefs);
    data.reindex(app.filter);
    $("hb-parse-text").value = data.store.weeklyGoals || "";
  } catch (e) {
    fail("Could not load your tasks: " + e.message);
    return;
  }

  try {
    app.scene = createScene($("hb-stage"), {
      onSelect: () => { renderInspector(app); },
      onFocus: () => { renderCrumbs(app); },
    });
  } catch (e) {
    fail("This browser could not start WebGL, so Home Base cannot render. " + e.message);
    return;
  }

  app.scene.setTheme(data.store.prefs.scene_theme || "space");
  app.scene.setQuality(data.store.prefs.quality || "high");
  app.scene.setFilter(app.filter);

  initHUD(app);
  initChat(app);
  app.refreshHUD();

  overlay.classList.add("gone");
  booted = true;
  if (wantsRunning) app.scene.start();
}

// Pause whenever the window is hidden - no point burning a GPU on a background tab.
document.addEventListener("visibilitychange", () => {
  if (!app.scene) return;
  if (document.hidden) app.scene.stop();
  else if (wantsRunning) app.scene.start();
});

watchColorTheme();

window.HomeBase = {
  enter() {
    wantsRunning = true;
    if (booted) { app.scene.start(); app.scene.resize(); return; }
    if (!booting) booting = boot();
  },
  leave() {
    wantsRunning = false;
    if (app.scene) app.scene.stop();
  },
  app,
};

// digest.js restores the last tab on DOMContentLoaded, which may already be this one.
if (typeof window.__digestActiveTab === "function" && window.__digestActiveTab() === "homebase") {
  window.HomeBase.enter();
}
