// The HUD: progress bar, filters, breadcrumbs, the inspector, and the task-source
// panel. Every mutation goes through the existing /api/digest/tasks/* endpoints, so
// anything changed here is instantly visible in the Daily Digest tab.

import * as data from "./data.js";
import { SCENES } from "./themes.js";

const $ = (id) => document.getElementById(id);

const ICONS = ["", "\u{1F680}", "\u{1F4BB}", "\u{1F9E0}", "\u{1F4DA}", "\u{1F4DD}", "\u{1F3AF}",
  "\u{1F3E0}", "\u{1F4B0}", "\u{1F4AA}", "\u{1F3A8}", "\u{1F52C}", "\u{1F5FA}", "\u{2699}",
  "\u{1F331}", "\u{1F525}", "\u{1F30D}", "\u{1F3C6}"];

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

let toastTimer = 0;

export function toast(message, bad = false) {
  const el = $("hb-toast");
  el.textContent = message;
  el.classList.toggle("bad", !!bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 5200 : 2600);
}

function showError(el, message) {
  if (!message) { el.hidden = true; el.textContent = ""; return; }
  el.textContent = message;
  el.hidden = false;
}

function busy(button, on, label) {
  if (!button) return;
  button.disabled = on;
  if (on) {
    button.dataset.label = button.textContent;
    button.textContent = label || "Working...";
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
  }
}

// --- progress ---------------------------------------------------------------

export function renderProgress(app) {
  const p = data.progress(app.filter);
  $("hb-count").textContent = `${p.done} / ${p.total}`;
  $("hb-pct").textContent = `${Math.round(p.pct * 100)}%`;
  const scope = app.filter.kind === "day"
    ? `due ${WEEKDAYS[app.filter.day]}`
    : data.FILTER_LABEL[app.filter.kind];
  $("hb-scope").textContent = p.total ? scope : `nothing ${scope}`;
  const fill = $("hb-bar-fill");
  fill.style.width = `${Math.round(p.pct * 100)}%`;
  fill.classList.toggle("full", p.total > 0 && p.done >= p.total);
}

// --- breadcrumbs ------------------------------------------------------------

export function renderCrumbs(app) {
  const box = $("hb-crumbs");
  box.textContent = "";
  const chain = app.scene.focusId ? data.chainOf(app.scene.focusId) : [];

  const add = (label, id, here) => {
    if (box.childNodes.length) {
      const sep = document.createElement("span");
      sep.className = "hb-crumb-sep";
      sep.textContent = "\u203A";
      box.appendChild(sep);
    }
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hb-crumb" + (here ? " here" : "");
    b.textContent = label;
    if (!here) b.addEventListener("click", () => app.focus(id));
    box.appendChild(b);
  };

  add("Home Base", null, chain.length === 0);
  chain.forEach((node, i) => add(node.text, node.id, i === chain.length - 1));
}

// --- inspector --------------------------------------------------------------

export function renderInspector(app) {
  const panel = $("hb-inspector");
  const id = app.selectedId;
  const node = id ? data.nodeById(id) : null;
  if (!node) { panel.hidden = true; return; }

  const entry = data.entryOf(id);
  const stats = data.statsOf(id);
  const meta = data.metaOf(id);
  const depth = entry ? entry.depth : 0;

  panel.hidden = false;
  showError($("hb-ins-err"), "");
  $("hb-ins-kind").textContent = stats.leaf
    ? (depth === 0 ? "Category" : "Task")
    : `${depth === 0 ? "Category" : "Task"} \u00B7 ${stats.done}/${stats.total} done`;
  $("hb-ins-text").value = node.text || "";
  $("hb-ins-done").checked = !!node.done;
  $("hb-ins-priority").value = node.priority || "medium";
  $("hb-ins-due").value = node.due || "";

  const est = $("hb-ins-est");
  est.value = data.fmtEst(node.est_minutes);
  est.disabled = depth !== 0;
  est.title = depth === 0 ? "Effort estimate" : "Estimates are kept on top-level entries";

  $("hb-ins-desc").value = meta.description || "";

  // icon picker
  const iconBox = $("hb-ins-icons");
  iconBox.textContent = "";
  ICONS.forEach((glyph) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hb-icon" + ((meta.icon || "") === glyph ? " active" : "");
    b.textContent = glyph || "\u2205";
    b.title = glyph ? "Use this icon" : "No icon";
    b.addEventListener("click", () => app.setMeta(id, { icon: glyph }));
    iconBox.appendChild(b);
  });

  // children
  const list = $("hb-ins-children");
  list.textContent = "";
  data.kids(node).forEach((kid) => {
    const kidStats = data.statsOf(kid.id);
    const row = document.createElement("div");
    row.className = "hb-child" + (kid.done ? " done" : "");

    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !!kid.done;
    check.title = "Mark done";
    check.addEventListener("change", () => app.update(kid.id, { done: check.checked }));
    row.appendChild(check);

    const text = document.createElement("span");
    text.className = "hb-child-text";
    text.textContent = kid.text;
    text.title = "Open this one";
    text.addEventListener("click", () => app.focus(kid.id));
    row.appendChild(text);

    if (!kidStats.leaf) {
      const n = document.createElement("span");
      n.className = "hb-child-n";
      n.textContent = `${kidStats.done}/${kidStats.total}`;
      row.appendChild(n);
    }

    const x = document.createElement("span");
    x.className = "hb-child-x";
    x.textContent = "\u00D7";
    x.title = "Delete";
    x.addEventListener("click", () => app.remove(kid.id, kid.text));
    row.appendChild(x);

    list.appendChild(row);
  });

  // saved progress notes
  const notes = $("hb-ins-notes");
  notes.textContent = "";
  (meta.notes || []).slice().reverse().forEach((note) => {
    const d = document.createElement("div");
    d.className = "hb-note";
    const time = document.createElement("time");
    time.textContent = note.at || "";
    d.appendChild(time);
    d.appendChild(document.createTextNode(note.text || ""));
    notes.appendChild(d);
  });
}

// --- wiring -----------------------------------------------------------------

function wireFilters(app) {
  $("hb-filters").querySelectorAll(".hb-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      app.setFilter({ kind: chip.dataset.filter, day: null });
      $("hb-day").value = "";
    });
  });

  const day = $("hb-day");
  WEEKDAYS.forEach((name, i) => {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = name;
    day.appendChild(o);
  });
  day.addEventListener("change", () => {
    if (day.value === "") app.setFilter({ kind: "week", day: null });
    else app.setFilter({ kind: "day", day: parseInt(day.value, 10) });
  });
}

export function syncFilterChips(app) {
  $("hb-filters").querySelectorAll(".hb-chip").forEach((chip) => {
    chip.classList.toggle("active", app.filter.kind === chip.dataset.filter);
  });
}

function wireTools(app) {
  const sceneSel = $("hb-scene");
  sceneSel.textContent = "";
  Object.values(SCENES).forEach((s) => {
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = s.label;
    sceneSel.appendChild(o);
  });
  sceneSel.value = SCENES[data.store.prefs.scene_theme] ? data.store.prefs.scene_theme : "space";
  sceneSel.addEventListener("change", () => {
    app.scene.setTheme(sceneSel.value);
    app.savePrefs({ scene_theme: sceneSel.value });
    renderCrumbs(app);
  });

  $("hb-quality").addEventListener("change", (e) => {
    app.scene.setQuality(e.target.value);
    app.savePrefs({ quality: e.target.value });
  });

  $("hb-reload").addEventListener("click", () => app.reload(true));
  $("hb-full").addEventListener("click", () => toggleFullscreen(app));

  $("hb-parse-open").addEventListener("click", () => {
    const panel = $("hb-parse");
    panel.hidden = !panel.hidden;
  });
  $("hb-parse-close").addEventListener("click", () => { $("hb-parse").hidden = true; });
  $("hb-ins-close").addEventListener("click", () => app.select(null));
}

function toggleFullscreen(app) {
  const root = $("hb-root");
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  if (root.requestFullscreen) {
    root.requestFullscreen().catch(() => {
      // Some browsers refuse; fall back to hiding the page chrome instead.
      document.body.classList.toggle("hb-focus");
      app.scene.resize();
    });
  } else {
    document.body.classList.toggle("hb-focus");
    app.scene.resize();
  }
}

function wireInspector(app) {
  const id = () => app.selectedId;

  const text = $("hb-ins-text");
  const commitText = () => {
    const node = data.nodeById(id());
    if (!node) return;
    const value = text.value.trim();
    if (!value || value === node.text) return;
    app.update(id(), { text: value });
  };
  text.addEventListener("blur", commitText);
  text.addEventListener("keydown", (e) => { if (e.key === "Enter") text.blur(); });

  $("hb-ins-done").addEventListener("change", (e) => app.update(id(), { done: e.target.checked }));
  $("hb-ins-priority").addEventListener("change", (e) => app.update(id(), { priority: e.target.value }));
  $("hb-ins-due").addEventListener("change", (e) => app.update(id(), { due: e.target.value }));

  const est = $("hb-ins-est");
  est.addEventListener("blur", () => app.update(id(), { est: est.value }));
  est.addEventListener("keydown", (e) => { if (e.key === "Enter") est.blur(); });

  const desc = $("hb-ins-desc");
  desc.addEventListener("blur", () => {
    const meta = data.metaOf(id());
    if ((meta.description || "") === desc.value) return;
    app.setMeta(id(), { description: desc.value });
  });

  const sub = $("hb-ins-subtext");
  sub.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const value = sub.value.trim();
    if (!value) return;
    sub.value = "";
    await app.addChild(id(), value);
  });

  $("hb-ins-ask").addEventListener("click", () => app.openChat(id()));
  $("hb-ins-delete").addEventListener("click", () => {
    const node = data.nodeById(id());
    if (node) app.remove(node.id, node.text);
  });

  $("hb-ins-breakdown").addEventListener("click", async () => {
    const button = $("hb-ins-breakdown");
    busy(button, true, "Thinking...");
    try {
      const res = await data.req("/api/homebase/breakdown", { id: id() });
      app.absorb(res);
      toast(res.added ? `Added ${res.added} steps` : "No new steps suggested");
    } catch (err) {
      showError($("hb-ins-err"), err.message);
    } finally {
      busy(button, false);
    }
  });
}

function wireParsePanel(app) {
  let parseMode = "llm";
  let writeMode = "merge";

  const seg = (boxId, attr, onPick) => {
    $(boxId).querySelectorAll(".hb-mini").forEach((b) => {
      b.addEventListener("click", () => {
        $(boxId).querySelectorAll(".hb-mini").forEach((o) => o.classList.remove("active"));
        b.classList.add("active");
        onPick(b.dataset[attr]);
      });
    });
  };
  seg("hb-parse-mode", "parse", (v) => { parseMode = v; });
  seg("hb-parse-write", "write", (v) => { writeMode = v; });

  $("hb-parse-run").addEventListener("click", async () => {
    const button = $("hb-parse-run");
    const err = $("hb-parse-err");
    const text = $("hb-parse-text").value;
    if (!text.trim()) { showError(err, "Add some tasks first."); return; }
    if (writeMode === "replace"
        && !confirm("Replace every weekly task with this list? Current tasks are removed.")) return;
    showError(err, "");
    busy(button, true, parseMode === "llm" ? "Asking the model..." : "Parsing...");
    try {
      const res = await data.req("/api/digest/tasks/derive", {
        weekly_text: text,
        use_llm: parseMode === "llm",
        replace: writeMode === "replace",
      });
      app.absorb(res, true);
      if (res.error_note) showError(err, res.error_note);
      toast(`${res.added} added${res.removed ? `, ${res.removed} replaced` : ""}`);
    } catch (e) {
      showError(err, e.message);
    } finally {
      busy(button, false);
    }
  });

  $("hb-add-cat").addEventListener("click", async () => {
    const name = prompt("New category or task name:");
    if (!name || !name.trim()) return;
    try {
      app.absorb(await data.req("/api/digest/tasks/add", { text: name.trim() }), true);
      toast("Added");
    } catch (e) { showError($("hb-parse-err"), e.message); }
  });

  $("hb-reset-progress").addEventListener("click", async () => {
    if (!confirm("Uncheck every task, keeping the structure?")) return;
    try {
      const res = await data.req("/api/homebase/reset-progress", {});
      app.absorb(res, true);
      toast(`Reset ${res.reset} item${res.reset === 1 ? "" : "s"}`);
    } catch (e) { showError($("hb-parse-err"), e.message); }
  });

  $("hb-clear-done").addEventListener("click", async () => {
    if (!confirm("Remove completed top-level entries?")) return;
    try {
      app.absorb(await data.req("/api/digest/tasks/clear-done", {}), true);
      toast("Cleared");
    } catch (e) { showError($("hb-parse-err"), e.message); }
  });

  $("hb-wipe").addEventListener("click", async () => {
    if (!confirm("Delete ALL weekly tasks? This cannot be undone.")) return;
    try {
      await data.req("/api/digest/clear", { category: "weekly_tasks" });
      await app.reload(true);
      toast("All tasks removed");
    } catch (e) { showError($("hb-parse-err"), e.message); }
  });
}

function wireKeys(app) {
  document.addEventListener("keydown", (e) => {
    if ($("view-homebase").hidden) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if (e.key === "Escape") {
      if (!$("hb-chat").hidden) { $("hb-chat").hidden = true; return; }
      if (!$("hb-parse").hidden) { $("hb-parse").hidden = true; return; }
      if (app.scene.focusId) { app.scene.ascend(); return; }
      app.select(null);
    } else if (e.key === "Backspace") {
      if (app.scene.focusId) { e.preventDefault(); app.scene.ascend(); }
    } else if (e.key === "f" || e.key === "F") {
      toggleFullscreen(app);
    }
  });

  document.addEventListener("fullscreenchange", () => {
    // The canvas lives inside the element that went fullscreen, so re-measure.
    setTimeout(() => app.scene.resize(), 60);
  });
}

export function initHUD(app) {
  wireFilters(app);
  wireTools(app);
  wireInspector(app);
  wireParsePanel(app);
  wireKeys(app);

  setTimeout(() => $("hb-hint").classList.add("gone"), 8000);
}

export { showError };
