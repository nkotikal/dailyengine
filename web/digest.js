"use strict";
// Daily Digest UI - isolated in an IIFE so it never collides with app.js globals.
(function () {
  const $ = (id) => document.getElementById(id);
  let loadedOnce = false;

  let memoryLoaded = false;

  const TAGLINES = {
    resume: "Paste a job description. Get a tailored, one-page, ATS-ready resume.",
    digest: "Feed it your goals and tasks. Get a compartmentalized digest emailed each morning.",
    memory: "Long-term context the engine remembers about you - build it up, prune it, reshape it.",
  };
  const TITLES = { resume: "ResumeForge", digest: "Daily Digest", memory: "Memory" };
  const VIEWS = ["resume", "digest", "memory"];

  function switchTab(which) {
    VIEWS.forEach((v) => {
      const active = v === which;
      $("view-" + v).hidden = !active;
      $("tab-" + v).classList.toggle("active", active);
      $("tab-" + v).setAttribute("aria-selected", String(active));
    });
    $("app-title").textContent = TITLES[which];
    $("app-tagline").textContent = TAGLINES[which];
    // Re-apply Korean UI after dynamic title/tagline swap.
    if (document.documentElement.getAttribute("lang") === "ko"
        && typeof window.applyUILang === "function") window.applyUILang("ko");
    try { localStorage.setItem("activeTab", which); } catch (e) { /* ignore */ }
    if (which === "digest" && !loadedOnce) { loadedOnce = true; loadStatus(); }
    if (which === "memory" && !memoryLoaded) { memoryLoaded = true; loadMemory(); }
  }

  function switchSub(which) {
    const tabs = document.querySelectorAll("#digest-subtabs .subtab");
    let valid = false;
    tabs.forEach((b) => { if (b.dataset.sub === which) valid = true; });
    if (!valid) which = "digest";
    tabs.forEach((b) => b.classList.toggle("active", b.dataset.sub === which));
    document.querySelectorAll("#view-digest .glass.panel[data-group]").forEach((p) => {
      p.hidden = p.dataset.group !== which;
    });
    try { localStorage.setItem("digestSub", which); } catch (e) { /* ignore */ }
  }

  function applyLanguageUI() {
    const lang = ($("d-language") && $("d-language").value) || "korean";
    if ($("d-korean-opts")) $("d-korean-opts").hidden = lang !== "korean";
    if ($("d-english-opts")) $("d-english-opts").hidden = lang !== "english";
    // Clear a stale lesson preview when switching languages.
    if ($("d-korean-out")) { $("d-korean-out").hidden = true; $("d-korean-out").innerHTML = ""; }
  }

  // Apply a per-user color theme (kept in sync with the header theme picker).
  function applyUserTheme(theme) {
    const t = theme || "aurora";
    if (t && t !== "aurora") document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    const sel = document.getElementById("theme-select");
    if (sel) sel.value = t;
    try { localStorage.setItem("rf-theme", t); } catch (e) { /* ignore */ }
  }

  function applyUserPattern(pattern) {
    const p = pattern || "moroccan";
    document.documentElement.setAttribute("data-pattern", p);
    const sel = document.getElementById("pattern-select");
    if (sel) sel.value = p;
    try { localStorage.setItem("rf-pattern", p); } catch (e) { /* ignore */ }
  }

  function chip(label, value, state) {
    const cls = state ? ` ${state}` : "";
    return `<span class="chip${cls}"><span class="dot"></span>${label}: <strong>${value}</strong></span>`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function showError(msg) {
    const el = $("d-error");
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  let trackerTypes = {};
  let newsSources = [];
  let newsTypes = {};

  function collectConfig() {
    return {
      about: $("d-about").value,
      weekly_goals: $("d-weekly-goals").value,
      longterm_goals: $("d-longterm-goals").value,
      goals: "",  // legacy field migrated into long-term; clear so it can't shadow
      tasks: $("d-tasks").value,
      email_to: $("d-email-to").value.trim(),
      send_time: $("d-send-time").value || "07:00",
      model: $("d-model").value || "",
      offline: $("d-offline").checked,
      enabled: $("d-enabled").checked,
      include_schedule: $("d-inc-schedule").checked,
      include_calendar: $("d-inc-calendar").checked,
      include_trackers: $("d-inc-trackers").checked,
      korean_enabled: $("d-korean").checked,
      korean_level: $("d-korean-level").value || "intermediate",
      language: ($("d-language") && $("d-language").value) || "korean",
      english_level: ($("d-english-level") && $("d-english-level").value) || "advanced",
      daily_capacity_hours: parseFloat($("d-capacity").value) || 6,
      news_enabled: $("d-news-enabled").checked,
      interests: $("d-interests").value.split(",").map((s) => s.trim()).filter(Boolean),
      news_sources: newsSources,
      openai_model: $("d-openai-model").value || "gpt-5.4-mini",
    };
  }

  function applyConfig(cfg) {
    $("d-about").value = cfg.about || "";
    $("d-weekly-goals").value = cfg.weekly_goals || "";
    // Migrate any legacy single "goals" field into long-term on first load.
    $("d-longterm-goals").value = cfg.longterm_goals || cfg.goals || "";
    $("d-tasks").value = cfg.tasks || "";
    $("d-email-to").value = cfg.email_to || "";
    $("d-send-time").value = cfg.send_time || "07:00";
    $("d-model").value = cfg.model || "";
    $("d-offline").checked = !!cfg.offline;
    $("d-enabled").checked = !!cfg.enabled;
    $("d-inc-schedule").checked = cfg.include_schedule !== false;
    $("d-inc-calendar").checked = cfg.include_calendar !== false;
    $("d-inc-trackers").checked = cfg.include_trackers !== false;
    $("d-korean").checked = !!cfg.korean_enabled;
    $("d-korean-level").value = cfg.korean_level || "intermediate";
    if ($("d-language")) $("d-language").value = cfg.language || "korean";
    if ($("d-english-level")) $("d-english-level").value = cfg.english_level || "advanced";
    applyLanguageUI();
    if (cfg.theme != null) applyUserTheme(cfg.theme);
    if (cfg.pattern != null) applyUserPattern(cfg.pattern);
    if (cfg.ui_lang != null && typeof window.applyUILang === "function") {
      try { localStorage.setItem("rf-lang", cfg.ui_lang); } catch (e) { /* ignore */ }
      window.applyUILang(cfg.ui_lang);
    }
    $("d-capacity").value = cfg.daily_capacity_hours != null ? cfg.daily_capacity_hours : 6;
    $("d-news-enabled").checked = cfg.news_enabled !== false;
    $("d-interests").value = (cfg.interests || []).join(", ");
    if (cfg.openai_model) $("d-openai-model").value = cfg.openai_model;
  }

  function renderChips(s) {
    const chips = [
      chip("AI", s.has_key ? "ready" : "offline only", s.has_key ? "good" : "bad"),
      chip("Email", s.email.configured ? "configured" : "not set", s.email.configured ? "good" : "bad"),
      chip("Auto-send", s.config.enabled ? "on" : "off", s.config.enabled ? "good" : "bad"),
      chip("Next", s.next_run, "good"),
    ];
    if (s.state && s.state.last_sent_date) {
      chips.push(chip("Last sent", s.state.last_sent_date, "good"));
    }
    if (s.replies_deferred_at) {
      chips.push(chip("Replies", "pending (AI was down)", "bad"));
    }
    const today = new Date().toISOString().slice(0, 10);
    if (s.schedule && s.schedule.for_date && s.schedule.for_date !== today
        && s.schedule.counts && s.schedule.counts.tasks) {
      chips.push(chip("Schedule", "for " + s.schedule.for_date, "need"));
    }
    $("digest-chips").innerHTML = chips.join("");

    const pill = $("d-email-pill");
    if (s.email.configured) {
      pill.textContent = `via ${s.email.host}`;
      pill.className = "pill good";
    } else {
      pill.textContent = "SMTP not set (.env)";
      pill.className = "pill need";
    }
  }

  function renderScheduleNote(s) {
    const note = $("d-schedule-note");
    const bits = [];
    if (s.config.enabled) {
      bits.push(`Auto-send is <strong>on</strong> - next digest <strong>${escapeHtml(s.next_run)}</strong>.`);
    } else {
      bits.push("Auto-send is <strong>off</strong>. Turn it on to email a digest every morning.");
    }
    if (!s.email.configured) {
      bits.push("Set <strong>SMTP_HOST</strong>/<strong>SMTP_USER</strong>/<strong>SMTP_PASSWORD</strong> in <strong>.env</strong> to enable email.");
    }
    if (s.state && s.state.last_error) {
      bits.push(`<span style="color:var(--danger)">Last error: ${escapeHtml(s.state.last_error)}</span>`);
    }
    bits.push("Digests are sent only while this local server is running.");
    note.innerHTML = bits.join(" ");
  }

  function renderUpdates(list) {
    const wrap = $("d-updates");
    $("d-pending-pill").textContent = `${list.length} new`;
    if (!list.length) {
      wrap.innerHTML = `<div class="d-updates-empty">No updates logged yet.</div>`;
      return;
    }
    wrap.innerHTML = list.map((u) => `
      <div class="d-update">
        <div>
          <div class="d-update-text">${escapeHtml(u.text)}</div>
          <div class="d-update-time">${escapeHtml(u.created_at || "")}</div>
        </div>
        <button class="d-update-x" data-id="${escapeHtml(u.id)}" title="Remove">&times;</button>
      </div>`).join("");
    wrap.querySelectorAll(".d-update-x").forEach((b) => {
      b.addEventListener("click", () => deleteUpdate(b.dataset.id));
    });
  }

  function renderReflection(refl) {
    const wrap = $("d-reflection");
    const pill = $("d-reflection-pill");
    if (!wrap) return;
    if (!refl || !(refl.accomplished || refl.blockers || refl.whats_next
                   || refl.mood || refl.progress_quality)) {
      wrap.innerHTML = `<div class="d-updates-empty">No reflection captured yet.</div>`;
      if (pill) pill.hidden = true;
      return;
    }
    if (pill) {
      pill.hidden = false;
      pill.textContent = refl.date || "";
    }
    const rows = [];
    const list = (label, arr) => {
      if (arr && arr.length) {
        rows.push(`<div class="d-refl-row"><span class="d-refl-k">${label}</span>`
          + `<span class="d-refl-v">${arr.map(escapeHtml).join(" · ")}</span></div>`);
      }
    };
    list("Did", refl.accomplished);
    if (refl.blockers && refl.blockers.length) {
      const b = refl.blockers.map((x) => `${escapeHtml(x.type || "")}: ${escapeHtml(x.text || "")}`);
      rows.push(`<div class="d-refl-row"><span class="d-refl-k">Blocked</span>`
        + `<span class="d-refl-v">${b.join(" · ")}</span></div>`);
    }
    list("Next", refl.whats_next);
    const meta = [];
    if (refl.mood) meta.push("mood: " + refl.mood);
    if (refl.progress_quality) meta.push("progress: " + refl.progress_quality);
    if (meta.length) {
      rows.push(`<div class="d-refl-row"><span class="d-refl-k">Read</span>`
        + `<span class="d-refl-v">${escapeHtml(meta.join(" · "))}</span></div>`);
    }
    wrap.innerHTML = rows.join("") || `<div class="d-updates-empty">No reflection captured yet.</div>`;
  }

  async function loadStatus() {
    try {
      const r = await fetch("/api/digest/status");
      const s = await r.json();
      if (!s.ok) { showError(s.error || "Could not load digest status."); return; }
      applyConfig(s.config);
      renderChips(s);
      renderScheduleNote(s);
      renderReflection(s.reflection);
      renderUpdates(s.pending_updates || []);
      trackerTypes = s.tracker_types || {};
      if (s.schedule && typeof s.schedule.raw === "string" && !$("d-schedule").value) {
        $("d-schedule").value = s.schedule.raw;
      }
      renderCalendar(s.calendar, s.schedule);
      renderTrackers(s.trackers || []);
      buildTrackerTypeSelect();
      renderKoreanPill(s.korean);
      renderReminders(s.reminders || []);
      renderWeeklyTasks(s.weekly_tasks || []);
      if (s.news) {
        newsSources = s.news.sources || [];
        newsTypes = s.news.source_types || {};
        renderNewsSources();
        buildNewsTypeSelect();
      }
    } catch (e) {
      $("digest-chips").innerHTML = chip("Server", "unreachable", "bad");
    }
  }

  // ---- weekly tasks ----
  const WT_PRIO = ["critical", "high", "medium", "low"];
  function wtError(msg) { const el = $("d-wt-error"); el.textContent = msg || ""; el.hidden = !msg; }
  function fmtEst(min) {
    min = parseInt(min || 0, 10);
    if (!min) return "";
    const h = Math.floor(min / 60), m = min % 60;
    return h && m ? `${h}h ${m}m` : (h ? `${h}h` : `${m}m`);
  }

  function renderWeeklyTasks(list) {
    const open = list.filter((t) => !t.done).length;
    $("d-wt-pill").textContent = `${open} open / ${list.length} total`;
    const wrap = $("d-wt-list");
    if (!list.length) {
      wrap.innerHTML = `<div class="d-wt-empty">No tasks yet. Add some, or click "Build from Goals this week".</div>`;
      return;
    }
    const order = { high: 0, medium: 1, low: 2 };
    const sorted = list.slice().sort((a, b) =>
      (a.done - b.done) || (order[a.priority] - order[b.priority]));
    wrap.innerHTML = sorted.map((t) => `
      <div class="d-wt-item p-${t.priority} ${t.done ? "done" : ""}">
        <input type="checkbox" class="d-wt-check" data-id="${t.id}" ${t.done ? "checked" : ""} />
        <div class="d-wt-body">
          <div class="d-wt-text" data-id="${t.id}">${escapeHtml(t.text)}</div>
          <div class="d-wt-meta">
            <button class="d-wt-prio-tag p-${t.priority}" data-id="${t.id}" title="Click to change importance">${escapeHtml(t.priority)}</button>
            <input type="date" class="d-wt-due-edit" data-id="${t.id}" value="${escapeHtml(t.due || "")}" title="Due date" />
            <input type="text" class="d-wt-est-edit" data-id="${t.id}" value="${escapeHtml(fmtEst(t.est_minutes))}" placeholder="est" title="Estimated time" />
          </div>
          ${renderSubtree(t.subtasks || [], t.id)}
        </div>
        <button class="d-wt-x" data-id="${t.id}" title="Delete">&times;</button>
      </div>`).join("");

    wrap.querySelectorAll(".d-wt-check").forEach((c) =>
      c.addEventListener("change", () => updateTask(c.dataset.id, { done: c.checked })));
    wrap.querySelectorAll(".d-wt-text").forEach((el) => {
      el.addEventListener("dblclick", () => { el.contentEditable = "true"; el.focus(); });
      el.addEventListener("blur", () => {
        if (el.contentEditable !== "true") return;
        el.contentEditable = "false";
        const v = el.textContent.trim();
        if (v) updateTask(el.dataset.id, { text: v });
      });
    });
    wrap.querySelectorAll(".d-wt-prio-tag").forEach((b) =>
      b.addEventListener("click", () => {
        const cur = b.textContent.trim();
        const next = WT_PRIO[(WT_PRIO.indexOf(cur) + 1) % WT_PRIO.length];
        updateTask(b.dataset.id, { priority: next });
      }));
    wrap.querySelectorAll(".d-wt-due-edit").forEach((el) =>
      el.addEventListener("change", () => updateTask(el.dataset.id, { due: el.value })));
    wrap.querySelectorAll(".d-wt-est-edit").forEach((el) =>
      el.addEventListener("change", () => updateTask(el.dataset.id, { est: el.value })));
    wrap.querySelectorAll(".d-wt-x").forEach((b) =>
      b.addEventListener("click", () => deleteTask(b.dataset.id)));
    // subtasks (any depth) - addressed by node id
    wrap.querySelectorAll(".d-wt-sub-check").forEach((c) =>
      c.addEventListener("change", () => wtPost("/api/digest/tasks/subtask/update",
        { id: c.dataset.id, fields: { done: c.checked } })));
    wrap.querySelectorAll(".d-wt-sub-text").forEach((el) => {
      el.addEventListener("dblclick", () => { el.contentEditable = "true"; el.focus(); });
      el.addEventListener("blur", () => {
        if (el.contentEditable !== "true") return;
        el.contentEditable = "false";
        const v = el.textContent.trim();
        if (v) wtPost("/api/digest/tasks/subtask/update", { id: el.dataset.id, fields: { text: v } });
      });
    });
    wrap.querySelectorAll(".d-wt-sub-due").forEach((el) =>
      el.addEventListener("change", () => wtPost("/api/digest/tasks/subtask/update",
        { id: el.dataset.id, fields: { due: el.value } })));
    wrap.querySelectorAll(".d-wt-sub-x").forEach((b) =>
      b.addEventListener("click", () => wtPost("/api/digest/tasks/subtask/delete", { id: b.dataset.id })));
    wrap.querySelectorAll(".d-wt-sub-addbtn").forEach((b) =>
      b.addEventListener("click", () => {
        const inp = b.nextElementSibling;
        if (inp) { inp.hidden = !inp.hidden; if (!inp.hidden) inp.focus(); }
      }));
    wrap.querySelectorAll(".d-wt-sub-input").forEach((inp) =>
      inp.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const v = inp.value.trim();
        if (v) wtPost("/api/digest/tasks/subtask/add", { parent_id: inp.dataset.parent, text: v });
      }));
  }

  // Recursively render a subtask tree (arbitrary depth).
  function renderSubtree(subs, parentId) {
    const inner = (subs || []).map((s) => `
      <div class="d-wt-subwrap">
        <div class="d-wt-sub ${s.done ? "done" : ""}">
          <input type="checkbox" class="d-wt-sub-check" data-id="${s.id}" ${s.done ? "checked" : ""} />
          <span class="d-wt-sub-text" data-id="${s.id}">${escapeHtml(s.text)}</span>
          <input type="date" class="d-wt-sub-due" data-id="${s.id}" value="${escapeHtml(s.due || "")}" title="Due date" />
          <button class="d-wt-sub-x" data-id="${s.id}" title="Delete">&times;</button>
        </div>
        ${renderSubtree(s.subtasks || [], s.id)}
      </div>`).join("");
    return `<div class="d-wt-subs">${inner}`
      + `<button type="button" class="d-wt-sub-addbtn" data-parent="${parentId}">+ subtask</button>`
      + `<input type="text" class="field d-wt-sub-input" data-parent="${parentId}" placeholder="subtask, then Enter" hidden /></div>`;
  }

  async function wtPost(path, body, btn, label) {
    if (btn) setBusy(btn, true, label);
    try {
      const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}) });
      const data = await r.json();
      if (!data.ok) { wtError(data.error || "Request failed."); return null; }
      wtError("");
      if (data.tasks) renderWeeklyTasks(data.tasks);
      return data;
    } catch (e) { wtError("Network error: " + e.message); return null; }
    finally { if (btn) setBusy(btn, false, label); }
  }

  function deriveTasks() {
    // Send the current (possibly unsaved) box so it derives from what's on screen.
    wtPost("/api/digest/tasks/derive", { weekly_text: $("d-weekly-goals").value },
           $("d-wt-derive"), 'Build from "Goals this week"');
  }
  function addTask() {
    const text = $("d-wt-input").value.trim();
    if (!text) return;
    wtPost("/api/digest/tasks/add", {
      text,
      priority: $("d-wt-priority").value,
      due: $("d-wt-due").value,
      est: $("d-wt-est").value,
    }).then((d) => {
      if (d) { $("d-wt-input").value = ""; $("d-wt-due").value = ""; $("d-wt-est").value = ""; }
    });
  }
  function updateTask(id, fields) { wtPost("/api/digest/tasks/update", { id, fields }); }
  function deleteTask(id) { wtPost("/api/digest/tasks/delete", { id }); }
  function clearDoneTasks() { wtPost("/api/digest/tasks/clear-done", {}); }

  // ---- news sources / interests / replies ----
  function buildNewsTypeSelect() {
    const sel = $("d-news-type");
    if (sel.options.length) return;
    sel.innerHTML = Object.entries(newsTypes)
      .map(([k, v]) => `<option value="${k}">${escapeHtml(v.label)}</option>`).join("");
  }

  function renderNewsSources() {
    const wrap = $("d-news-list");
    if (!newsSources.length) {
      wrap.innerHTML = `<div class="d-updates-empty">No sources. Add one below.</div>`;
      return;
    }
    wrap.innerHTML = newsSources.map((s, i) => `
      <div class="d-tracker-item">
        <div><div class="d-tracker-meta"><span class="d-tag">${escapeHtml(s.type)}</span> ${escapeHtml(s.name || s.type)}</div>
          <div class="d-tracker-sub">${escapeHtml(s.url || "")}</div></div>
        <div class="d-tracker-controls">
          <label class="switch" title="Enabled"><input type="checkbox" class="d-news-toggle" data-i="${i}" ${s.enabled !== false ? "checked" : ""} />
            <span class="track"><span class="thumb"></span></span></label>
          <button class="d-update-x" data-i="${i}" title="Remove">&times;</button>
        </div>
      </div>`).join("");
    wrap.querySelectorAll(".d-news-toggle").forEach((c) =>
      c.addEventListener("change", () => { newsSources[+c.dataset.i].enabled = c.checked; saveNews(); }));
    wrap.querySelectorAll(".d-update-x").forEach((b) =>
      b.addEventListener("click", () => { newsSources.splice(+b.dataset.i, 1); renderNewsSources(); saveNews(); }));
  }

  function addNewsSource() {
    const type = $("d-news-type").value;
    if (!type) return;
    const def = newsTypes[type] || {};
    newsSources.push({
      id: type + "-" + Date.now().toString(36),
      type,
      name: $("d-news-name").value.trim() || (def.label || type),
      url: $("d-news-url").value.trim() || def.default_url || "",
      enabled: true,
    });
    $("d-news-name").value = ""; $("d-news-url").value = "";
    renderNewsSources();
    saveNews();
  }

  async function saveNews(showNote) {
    const r = await fetch("/api/digest/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });
    await r.json();
    if (showNote) {
      const n = $("d-news-note"); n.hidden = false; n.textContent = "Saved.";
      setTimeout(() => { n.hidden = true; }, 1800);
    }
  }

  async function processReplies() {
    const btn = $("d-replies-process");
    const n = $("d-news-note");
    btn.disabled = true; n.hidden = false; n.textContent = "Checking your replies...";
    try {
      const r = await fetch("/api/digest/replies/process", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      if (!data.ok) { n.textContent = data.error || "Failed."; return; }
      if (data.skipped) { n.textContent = "Email replies aren't configured (IMAP)."; return; }
      const applied = (data.applied || []).map((a) => a.note).filter(Boolean);
      n.innerHTML = `Processed ${data.processed} repl${data.processed === 1 ? "y" : "ies"}.` +
        (applied.length ? "<br>" + applied.map(escapeHtml).join("<br>") : "");
      loadStatus();
    } catch (e) { n.textContent = "Network error: " + e.message; }
    finally { btn.disabled = false; }
  }

  // ---- clear / reset ----
  async function clearCategory(category, label, strong) {
    const msg = strong
      ? `Reset ${label}? This wipes all content (delivery settings are kept) and can't be undone.`
      : `Clear ${label}? This can't be undone.`;
    if (!confirm(msg)) return;
    const re = $("d-reset-error");
    if (re) re.hidden = true;
    try {
      const r = await fetch("/api/digest/clear", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category }),
      });
      const data = await r.json();
      if (!data.ok) { if (re) { re.textContent = data.error || "Clear failed."; re.hidden = false; } return; }
      // The schedule textarea has a load-guard, so clear it directly.
      if (category === "schedule" || category === "all") {
        $("d-schedule").value = "";
        $("d-parsed").hidden = true;
      }
      // Refresh whatever views are affected.
      loadStatus();
      if (memoryLoaded) loadMemory();
    } catch (e) {
      if (re) { re.textContent = "Network error: " + e.message; re.hidden = false; }
    }
  }

  // ---- schedule / calendar ----
  function renderCalendar(cal, sched) {
    const pill = $("d-cal-pill");
    if (cal && cal.configured) {
      pill.textContent = "calendar connected";
      pill.className = "pill good";
    } else {
      pill.textContent = "calendar not linked";
      pill.className = "pill need";
    }
    const note = $("d-cal-note");
    const bits = [];
    if (sched && sched.counts && sched.counts.tasks) {
      bits.push(`Parsed <strong>${sched.counts.tasks}</strong> tasks in <strong>${sched.counts.blocks}</strong> time blocks (${sched.counts.important} important).`);
    }
    if (!(cal && cal.configured)) {
      bits.push("Add <strong>GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN</strong> to <strong>.env</strong> to push events (you can point this at a separate calendar account any time).");
    }
    note.innerHTML = bits.join(" ");
  }

  function renderParsed(parsed) {
    const wrap = $("d-parsed");
    if (!parsed || !parsed.blocks || !parsed.blocks.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const mark = (n) => n.critical ? "\u203c\ufe0f " : (n.important ? "\u2605 " : "");
    wrap.innerHTML = parsed.blocks.filter(b => b.tasks.length).map((b) => `
      <div class="d-blk">
        <div class="d-blk-time">${escapeHtml(b.time_str)}</div>
        ${b.tasks.map((t) => `
          <div class="d-blk-task ${t.critical ? "crit" : (t.important ? "imp" : "")}">${mark(t)}${escapeHtml(t.text)}</div>
          ${t.subtasks.map((s) => `<div class="d-blk-sub">${mark(s) || "\u00b7 "}${escapeHtml(s.text)}</div>`).join("")}
        `).join("")}
      </div>`).join("");
  }

  async function parseSchedule() {
    showError("");
    const btn = $("d-parse");
    setBusy(btn, true, "Parse & save");
    try {
      const r = await fetch("/api/digest/schedule", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw: $("d-schedule").value }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Parse failed."); return; }
      renderParsed(data.parsed);
      loadStatus();
    } catch (e) { showError("Network error: " + e.message); }
    finally { setBusy(btn, false, "Parse & save"); }
  }

  async function pushCalendar() {
    showError("");
    try {
      const r = await fetch("/api/digest/schedule/push", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Push failed."); return; }
      const st = $("d-save-status");
      st.textContent = `Pushed ${data.created}/${data.total} events`;
      setTimeout(() => { st.textContent = ""; }, 4000);
      if (data.errors && data.errors.length) showError(data.errors.join(" "));
    } catch (e) { showError("Network error: " + e.message); }
  }

  // ---- trackers ----
  function buildTrackerTypeSelect() {
    const sel = $("d-tracker-type");
    if (sel.options.length) return;  // already built
    sel.innerHTML = Object.entries(trackerTypes)
      .map(([k, v]) => `<option value="${k}">${escapeHtml(v.label)}</option>`).join("");
    sel.addEventListener("change", buildTrackerFields);
    buildTrackerFields();
  }

  function buildTrackerFields() {
    const type = $("d-tracker-type").value;
    const def = trackerTypes[type];
    const wrap = $("d-tracker-fields");
    if (!def) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = def.fields.map((f) => {
      const id = `d-tf-${f.key}`;
      if (f.type === "select") {
        return `<label class="select-wrap"><span>${escapeHtml(f.label)}</span>
          <select id="${id}" class="field select">${f.options.map(o => `<option value="${o}">${o}</option>`).join("")}</select></label>`;
      }
      if (f.type === "bool") {
        return `<label class="d-check"><input type="checkbox" id="${id}" checked /> ${escapeHtml(f.label)}</label>`;
      }
      return `<label class="select-wrap"><span>${escapeHtml(f.label)}</span>
        <input type="text" id="${id}" class="field" placeholder="${escapeHtml(f.placeholder || "")}" /></label>`;
    }).join("");
  }

  function collectTrackerConfig() {
    const type = $("d-tracker-type").value;
    const def = trackerTypes[type];
    const cfg = {};
    (def ? def.fields : []).forEach((f) => {
      const el = $(`d-tf-${f.key}`);
      if (!el) return;
      cfg[f.key] = f.type === "bool" ? el.checked : el.value.trim();
    });
    return { type, name: $("d-tracker-name").value.trim(), config: cfg };
  }

  function renderTrackers(list) {
    $("d-trackers-pill").textContent = `${list.filter(t => t.enabled).length} active`;
    const wrap = $("d-tracker-list");
    if (!list.length) { wrap.innerHTML = `<div class="d-updates-empty">No trackers yet. Add one below.</div>`; return; }
    wrap.innerHTML = list.map((t) => {
      const cfgStr = Object.entries(t.config || {}).map(([k, v]) => `${k}: ${v}`).join("  ·  ");
      return `<div class="d-tracker-item">
        <div>
          <div class="d-tracker-meta"><span class="d-tag">${escapeHtml(t.type)}</span> ${escapeHtml(t.name)}</div>
          <div class="d-tracker-sub">${escapeHtml(cfgStr)}</div>
        </div>
        <div class="d-tracker-controls">
          <label class="switch" title="Enabled">
            <input type="checkbox" data-id="${t.id}" class="d-tr-toggle" ${t.enabled ? "checked" : ""} />
            <span class="track"><span class="thumb"></span></span>
          </label>
          <button class="d-update-x" data-id="${t.id}" title="Remove">&times;</button>
        </div>
      </div>`;
    }).join("");
    wrap.querySelectorAll(".d-tr-toggle").forEach((c) =>
      c.addEventListener("change", () => toggleTracker(c.dataset.id, c.checked)));
    wrap.querySelectorAll(".d-update-x").forEach((b) =>
      b.addEventListener("click", () => deleteTracker(b.dataset.id)));
  }

  // ---- reminders ----
  function _reminderWhen(due) {
    if (!due) return { label: "no date", cls: "" };
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const d = new Date(due + "T00:00:00");
    const days = Math.round((d - today) / 86400000);
    if (days < 0) return { label: `overdue ${-days}d (${due})`, cls: "imp" };
    if (days === 0) return { label: `due today (${due})`, cls: "imp" };
    if (days <= 2) return { label: `in ${days}d (${due})`, cls: "imp" };
    return { label: `in ${days}d (${due})`, cls: "" };
  }

  function renderReminders(list) {
    const active = list.filter((r) => !r.done);
    $("d-reminders-pill").textContent = `${active.length} active`;
    const wrap = $("d-reminder-list");
    if (!list.length) { wrap.innerHTML = `<div class="d-updates-empty">No reminders yet. Add one below.</div>`; return; }
    const sorted = list.slice().sort((a, b) => {
      const da = a.due || "9999", db = b.due || "9999";
      return da < db ? -1 : da > db ? 1 : 0;
    });
    wrap.innerHTML = sorted.map((r) => {
      const w = _reminderWhen(r.due);
      return `<div class="d-tracker-item ${r.done ? "d-done" : ""}">
        <div>
          <div class="d-tracker-meta">
            <span class="d-tag tag-${r.priority}">${escapeHtml(r.priority)}</span>
            ${escapeHtml(r.text)}
          </div>
          <div class="d-tracker-sub ${w.cls === "imp" ? "d-overdue" : ""}">${escapeHtml(w.label)}</div>
        </div>
        <div class="d-tracker-controls">
          <label class="switch" title="Mark done">
            <input type="checkbox" data-id="${r.id}" class="d-rm-done" ${r.done ? "checked" : ""} />
            <span class="track"><span class="thumb"></span></span>
          </label>
          <button class="d-update-x" data-id="${r.id}" title="Remove">&times;</button>
        </div>
      </div>`;
    }).join("");
    wrap.querySelectorAll(".d-rm-done").forEach((c) =>
      c.addEventListener("change", () => updateReminder(c.dataset.id, { done: c.checked })));
    wrap.querySelectorAll(".d-update-x").forEach((b) =>
      b.addEventListener("click", () => deleteReminder(b.dataset.id)));
  }

  async function addReminder() {
    showError("");
    const text = $("d-reminder-text").value.trim();
    if (!text) { showError("Enter a reminder."); return; }
    const btn = $("d-reminder-add");
    setBusy(btn, true, "Add reminder");
    try {
      const r = await fetch("/api/digest/reminder/add", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text, due: $("d-reminder-due").value || "",
          priority: $("d-reminder-priority").value || "medium",
        }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Could not add reminder."); return; }
      $("d-reminder-text").value = "";
      $("d-reminder-due").value = "";
      renderReminders(data.reminders || []);
    } catch (e) { showError("Network error: " + e.message); }
    finally { setBusy(btn, false, "Add reminder"); }
  }

  async function updateReminder(id, fields) {
    const r = await fetch("/api/digest/reminder/update", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, fields }),
    });
    const data = await r.json();
    renderReminders(data.reminders || []);
  }

  async function deleteReminder(id) {
    const r = await fetch("/api/digest/reminder/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await r.json();
    renderReminders(data.reminders || []);
  }

  async function addTracker() {
    showError("");
    const t = collectTrackerConfig();
    const btn = $("d-tracker-save");
    setBusy(btn, true, "Add tracker");
    try {
      const r = await fetch("/api/digest/tracker/add", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(t),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Could not add tracker."); return; }
      $("d-tracker-name").value = "";
      buildTrackerFields();
      $("d-tracker-results").hidden = true;
      renderTrackers(data.trackers || []);
      $("d-trackers-pill").textContent = `${(data.trackers || []).filter(x => x.enabled).length} active`;
    } catch (e) { showError("Network error: " + e.message); }
    finally { setBusy(btn, false, "Add tracker"); }
  }

  async function testTracker() {
    showError("");
    const t = collectTrackerConfig();
    const out = $("d-tracker-results");
    out.hidden = false;
    out.innerHTML = "Testing...";
    try {
      const r = await fetch("/api/digest/tracker/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tracker: { id: "test", ...t } }),
      });
      const data = await r.json();
      if (!data.ok) { out.innerHTML = `<span style="color:var(--danger)">${escapeHtml(data.error || "Test failed.")}</span>`; return; }
      if (!data.findings.length) { out.innerHTML = "No findings right now (that's normal — you'll be notified of new items)."; return; }
      out.innerHTML = data.findings.map((f) => `<div>• <strong>${escapeHtml(f.source || "")}</strong> ${escapeHtml(f.text || "")}</div>`).join("");
    } catch (e) { out.innerHTML = `<span style="color:var(--danger)">Network error: ${escapeHtml(e.message)}</span>`; }
  }

  async function toggleTracker(id, enabled) {
    await fetch("/api/digest/tracker/update", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, fields: { enabled } }),
    });
    loadStatus();
  }

  async function deleteTracker(id) {
    await fetch("/api/digest/tracker/delete", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    loadStatus();
  }

  // ---- language practice ----
  function renderKoreanPill(k) {
    const pill = $("d-korean-pill");
    const lang = (k && k.language) || "korean";
    if (k && k.enabled) {
      if (lang === "english") {
        pill.textContent = `English · ${typeof k.progress === "string" ? k.progress : "on"}`;
      } else {
        pill.textContent = `${k.level} · ${k.seen_vocab} learned`;
      }
      pill.className = "pill good";
    } else {
      pill.textContent = "off";
      pill.className = "pill ghost";
    }
    // The structured progress bars only apply to the Korean syllabus.
    const prog = (lang === "korean" && k && typeof k.progress === "object") ? k.progress : null;
    const wrap = $("d-korean-progress");
    if (prog) {
      const gpct = prog.grammar_total ? Math.round(100 * prog.grammar_done / prog.grammar_total) : 0;
      const vpct = prog.vocab_total ? Math.round(100 * prog.vocab_done / prog.vocab_total) : 0;
      wrap.innerHTML = `
        <div class="d-prog-row"><span>Grammar syllabus</span><span>${prog.grammar_done}/${prog.grammar_total}</span></div>
        <div class="d-prog-bar"><span style="width:${gpct}%"></span></div>
        <div class="d-prog-row"><span>Vocabulary deck</span><span>${prog.vocab_done}/${prog.vocab_total}</span></div>
        <div class="d-prog-bar"><span style="width:${vpct}%"></span></div>
        <div class="d-prog-meta">${prog.tracked_items} items in spaced repetition · ${prog.reviews_due} due for review today</div>`;
    } else {
      wrap.innerHTML = "";
    }
  }

  async function setPlacement() {
    showError("");
    try {
      const r = await fetch("/api/digest/korean/placement", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level: $("d-korean-level").value }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Placement failed."); return; }
      const st = $("d-save-status");
      st.textContent = "Placement set";
      setTimeout(() => { st.textContent = ""; }, 2500);
      loadStatus();
    } catch (e) { showError("Network error: " + e.message); }
  }

  async function previewKorean() {
    showError("");
    await saveConfig(true);
    const btn = $("d-korean-preview");
    setBusy(btn, true, "Preview today's lesson");
    try {
      const r = await fetch("/api/digest/korean/preview", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Could not generate lesson."); return; }
      if (data.language === "english") renderEnglish(data.lesson);
      else renderKorean(data.lesson);
    } catch (e) { showError("Network error: " + e.message); }
    finally { setBusy(btn, false, "Preview today's lesson"); }
  }

  function renderEnglish(lesson) {
    const out = $("d-korean-out");
    out.hidden = false;
    const words = (lesson && lesson.words) || [];
    let html = `<div class="d-k-label">Vocabulary${lesson && lesson.theme ? " · " + escapeHtml(lesson.theme) : ""}</div>`;
    html += words.map((w) => `<div class="d-k-card">
      <div><span class="d-k-ko">${escapeHtml(w.word)}</span>${w.pos ? ` <em>(${escapeHtml(w.pos)})</em>` : ""}</div>
      <div class="d-k-en">${escapeHtml(w.definition || "")}</div>
      ${w.example ? `<div class="d-k-ex">${escapeHtml(w.example)}</div>` : ""}
      ${w.synonyms ? `<div class="d-k-ex">syn: ${escapeHtml(w.synonyms)}</div>` : ""}
    </div>`).join("");
    out.innerHTML = html || `<div class="d-updates-empty">No words.</div>`;
  }

  function renderKorean(lesson) {
    const out = $("d-korean-out");
    out.hidden = false;
    let html = "";
    if (lesson.vocab && lesson.vocab.length) {
      html += `<div class="d-k-label">Vocabulary</div>`;
      html += lesson.vocab.map((v) => `<div class="d-k-card">
        <div><span class="d-k-ko">${escapeHtml(v.korean)}</span><span class="d-k-rom">${escapeHtml(v.romanization)}</span></div>
        <div class="d-k-en">${escapeHtml(v.english)}${v.pos ? ` <em>(${escapeHtml(v.pos)})</em>` : ""}</div>
        ${v.example_ko ? `<div class="d-k-ex">${escapeHtml(v.example_ko)} — ${escapeHtml(v.example_en)}</div>` : ""}
      </div>`).join("");
    }
    if (lesson.grammar && lesson.grammar.length) {
      html += `<div class="d-k-label">Grammar</div>`;
      html += lesson.grammar.map((g) => `<div class="d-k-card">
        <div class="d-k-ko">${escapeHtml(g.point)}</div>
        <div class="d-k-en">${escapeHtml(g.english)}</div>
        ${g.example_ko ? `<div class="d-k-ex">${escapeHtml(g.example_ko)} — ${escapeHtml(g.example_en)}</div>` : ""}
      </div>`).join("");
    }
    if (lesson.review && lesson.review.length) {
      html += `<div class="d-k-label">Review (spaced repetition)</div>`;
      html += lesson.review.map((r) => `<div class="d-k-card">
        <div class="d-k-ko" style="font-size:15px">${escapeHtml(r.item)}</div>
        <div class="d-k-en">${escapeHtml(r.prompt)} <em>${escapeHtml(r.answer)}</em></div>
        ${r.example_ko ? `<div class="d-k-ex">${escapeHtml(r.example_ko)}</div>` : ""}
      </div>`).join("");
    }
    if (lesson.tip) html += `<div class="d-tracker-results">💡 ${escapeHtml(lesson.tip)}</div>`;
    out.innerHTML = html;
  }

  async function saveConfig(silent) {
    showError("");
    try {
      const r = await fetch("/api/digest/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collectConfig()),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Save failed."); return false; }
      if (!silent) {
        const st = $("d-save-status");
        st.textContent = "Saved";
        setTimeout(() => { st.textContent = ""; }, 1800);
      }
      loadStatus();
      return true;
    } catch (e) {
      showError("Network error: " + e.message);
      return false;
    }
  }

  async function addUpdate() {
    const inp = $("d-update-input");
    const text = inp.value.trim();
    if (!text) return;
    showError("");
    try {
      const r = await fetch("/api/digest/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Could not add update."); return; }
      inp.value = "";
      loadStatus();
    } catch (e) {
      showError("Network error: " + e.message);
    }
  }

  async function deleteUpdate(id) {
    try {
      await fetch("/api/digest/update/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      loadStatus();
    } catch (e) {
      showError("Network error: " + e.message);
    }
  }

  function setBusy(btn, busy, label) {
    btn.disabled = busy;
    btn.querySelector(".btn-label").textContent = busy ? "Working..." : label;
    const sp = btn.querySelector(".spinner");
    if (sp) sp.hidden = !busy;
  }

  async function preview() {
    showError("");
    await saveConfig(true);
    const btn = $("d-preview");
    setBusy(btn, true, "Preview digest");
    try {
      const r = await fetch("/api/digest/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: collectConfig() }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Preview failed."); return; }
      $("d-preview-frame").srcdoc = data.html;
      const meta = $("d-preview-meta");
      meta.hidden = false;
      const mode = data.used_llm ? "AI" : "offline";
      meta.textContent = `${mode} · ${data.update_count} update(s)`;
      $("d-preview-wrap").hidden = false;
      if (data.warning) showError(data.warning);
    } catch (e) {
      showError("Network error: " + e.message);
    } finally {
      setBusy(btn, false, "Preview digest");
    }
  }

  async function sendNow() {
    showError("");
    if (!$("d-email-to").value.trim()) {
      showError("Add a recipient email address first.");
      return;
    }
    await saveConfig(true);
    const btn = $("d-send");
    setBusy(btn, true, "Send now");
    try {
      const r = await fetch("/api/digest/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: collectConfig() }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Send failed."); return; }
      const st = $("d-save-status");
      st.textContent = `Sent to ${data.sent_to}`;
      setTimeout(() => { st.textContent = ""; }, 3000);
      if (data.warning) showError(data.warning);
      loadStatus();
    } catch (e) {
      showError("Network error: " + e.message);
    } finally {
      setBusy(btn, false, "Send now");
    }
  }

  // Resend: save the current schedule (in case you just added/edited it) and
  // settings, then rebuild and re-email today's digest with the updated info.
  async function resendNow() {
    showError("");
    if (!$("d-email-to").value.trim()) {
      showError("Add a recipient email address first.");
      return;
    }
    const btn = $("d-resend");
    setBusy(btn, true, "Resend with updates");
    try {
      const raw = $("d-schedule").value;
      if (raw && raw.trim()) {
        const sr = await fetch("/api/digest/schedule", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ raw }),
        });
        const sd = await sr.json();
        if (sd.ok && sd.parsed) renderParsed(sd.parsed);
      }
      await saveConfig(true);
      const r = await fetch("/api/digest/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: collectConfig() }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Resend failed."); return; }
      const st = $("d-save-status");
      st.textContent = `Resent to ${data.sent_to}`;
      setTimeout(() => { st.textContent = ""; }, 3000);
      if (data.warning) showError(data.warning);
      loadStatus();
    } catch (e) {
      showError("Network error: " + e.message);
    } finally {
      setBusy(btn, false, "Resend with updates");
    }
  }

  // ============================ MEMORY ============================
  let memories = [];
  let memCategories = [];
  let memFilter = "all";
  let memResumeB64 = null;

  function mError(msg) { const el = $("m-error"); el.textContent = msg || ""; el.hidden = !msg; }

  function renderMemory() {
    $("m-count-pill").textContent = `${memories.length} memories`;
    // filter chips
    const cats = ["all", ...Array.from(new Set(memories.map((m) => m.category))).sort()];
    $("m-filter").innerHTML = cats.map((c) =>
      `<span class="m-chip ${c === memFilter ? "active" : ""}" data-cat="${escapeHtml(c)}">${escapeHtml(c)}${c === "all" ? "" : ` (${memories.filter(m => m.category === c).length})`}</span>`
    ).join("");
    $("m-filter").querySelectorAll(".m-chip").forEach((ch) =>
      ch.addEventListener("click", () => { memFilter = ch.dataset.cat; renderMemory(); }));

    const shown = memories
      .filter((m) => memFilter === "all" || m.category === memFilter)
      .sort((a, b) => (b.importance || 0) - (a.importance || 0));
    const list = $("m-list");
    if (!shown.length) { list.innerHTML = `<div class="m-empty">No memories yet. Upload a resume or tell it about yourself.</div>`; return; }
    list.innerHTML = shown.map((m) => {
      const imp = m.importance == null ? 60 : m.importance;
      const impColor = imp >= 66 ? "var(--ok)" : (imp >= 33 ? "var(--warn)" : "var(--text-faint)");
      const comp = m.source === "compressed" ? ` · <span style="color:var(--accent)">compressed</span>` : "";
      return `
      <div class="m-item">
        <div class="m-item-body">
          <div class="m-item-text" data-id="${m.id}">${escapeHtml(m.text)}</div>
          <div class="m-item-meta">
            <span class="m-cat" data-id="${m.id}" title="Click to change category">${escapeHtml(m.category)}</span>
            <span class="m-imp" title="Importance"><span style="color:${impColor}">●</span> ${imp}</span>
            <span class="m-time">${escapeHtml((m.updated_at || "").slice(0, 10))}${comp}</span>
          </div>
        </div>
        <div class="m-controls">
          <button class="d-update-x" data-id="${m.id}" title="Delete">&times;</button>
        </div>
      </div>`;
    }).join("");
    // inline edit text on blur
    list.querySelectorAll(".m-item-text").forEach((el) => {
      el.addEventListener("dblclick", () => { el.contentEditable = "true"; el.focus(); });
      el.addEventListener("blur", () => {
        if (el.contentEditable !== "true") return;
        el.contentEditable = "false";
        const m = memories.find((x) => x.id === el.dataset.id);
        const val = el.textContent.trim();
        if (m && val && val !== m.text) updateMemory(el.dataset.id, { text: val });
      });
    });
    list.querySelectorAll(".m-cat").forEach((el) =>
      el.addEventListener("click", () => {
        const next = prompt("Category for this memory:", el.textContent.trim());
        if (next && next.trim()) updateMemory(el.dataset.id, { category: next.trim() });
      }));
    list.querySelectorAll(".d-update-x").forEach((b) =>
      b.addEventListener("click", () => deleteMemory(b.dataset.id)));
  }

  function applyMemoryPayload(data) {
    memories = data.memories || [];
    if (data.categories) memCategories = data.categories;
    if (data.profile_base != null && document.activeElement !== $("m-profile")) {
      $("m-profile").value = data.profile_base;
    }
    renderMemory();
    $("memory-chips").innerHTML =
      chip("Memories", String(memories.length), "good") +
      chip("Categories", String(new Set(memories.map(m => m.category)).size || 0), "good");
  }

  async function loadMemory() {
    try {
      const r = await fetch("/api/memory");
      applyMemoryPayload(await r.json());
    } catch (e) { mError("Could not load memory: " + e.message); }
  }

  async function memPost(path, body, btn, label) {
    if (btn) setBusy(btn, true, label);
    try {
      const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      const data = await r.json();
      if (!data.ok) { mError(data.error || "Request failed."); return null; }
      mError("");
      return data;
    } catch (e) { mError("Network error: " + e.message); return null; }
    finally { if (btn) setBusy(btn, false, label); }
  }

  async function updateMemory(id, fields) {
    const data = await memPost("/api/memory/update", { id, fields });
    if (data) applyMemoryPayload(data);
  }
  async function deleteMemory(id) {
    const data = await memPost("/api/memory/delete", { id });
    if (data) applyMemoryPayload(data);
  }
  async function addDirectMemory() {
    const text = $("m-command").value.trim();
    if (!text) { mError("Type something to add first."); return; }
    const data = await memPost("/api/memory/add", { text, category: "fact" }, $("m-add-direct"), "Add as one memory");
    if (data) { $("m-command").value = ""; applyMemoryPayload(data); }
  }
  async function applyMemoryCommand() {
    const command = $("m-command").value.trim();
    if (!command) { mError("Type an instruction first."); return; }
    const data = await memPost("/api/memory/command", { command }, $("m-apply"), "Apply");
    if (data) {
      $("m-command").value = "";
      applyMemoryPayload(data);
      const note = $("m-change-note");
      note.hidden = false;
      const a = data.applied || {};
      note.innerHTML = `<strong>${escapeHtml(data.summary || "Done.")}</strong> ` +
        `(+${a.added || 0} added, ${a.updated || 0} updated, ${a.removed || 0} removed)`;
    }
  }

  function mFileToBase64(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result).split(",")[1]);
      r.onerror = rej; r.readAsDataURL(file);
    });
  }
  function mFileToText(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result));
      r.onerror = rej; r.readAsText(file);
    });
  }
  async function onMemResumeFile(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    mError("");
    const chipEl = $("m-file-chip");
    chipEl.hidden = false;
    chipEl.innerHTML = `${escapeHtml(f.name)} <span class="chip-x" title="Remove">&times;</span>`;
    chipEl.querySelector(".chip-x").addEventListener("click", () => {
      memResumeB64 = null; chipEl.hidden = true; $("m-resume-file").value = "";
    });
    try {
      if (f.name.toLowerCase().endsWith(".pdf")) {
        memResumeB64 = await mFileToBase64(f);
      } else {
        $("m-resume-text").value = await mFileToText(f);
        memResumeB64 = null;
      }
    } catch (err) { mError("Could not read that file."); }
  }
  async function ingestResume() {
    const text = $("m-resume-text").value.trim();
    if (!memResumeB64 && !text) { mError("Upload a resume PDF or paste resume text first."); return; }
    const body = memResumeB64 ? { resume_pdf_base64: memResumeB64 } : { text };
    const data = await memPost("/api/memory/resume", body, $("m-ingest"), "Add to memory");
    if (data) {
      $("m-resume-text").value = "";
      memResumeB64 = null;
      $("m-file-chip").hidden = true;
      $("m-resume-file").value = "";
      applyMemoryPayload(data);
      const note = $("m-change-note");
      note.hidden = false;
      note.innerHTML = `<strong>Added ${data.added} memories from your resume.</strong>`;
    }
  }

  // Let Tab insert a real tab (for nesting) in outline-style textareas.
  function enableTabKey(id) {
    const el = $(id);
    if (!el) return;
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Tab" || e.shiftKey) return;
      e.preventDefault();
      const s = el.selectionStart, end = el.selectionEnd;
      el.value = el.value.slice(0, s) + "\t" + el.value.slice(end);
      el.selectionStart = el.selectionEnd = s + 1;
    });
  }

  async function saveProfileBase() {
    const data = await memPost("/api/memory/profile", { text: $("m-profile").value });
    if (data) {
      const st = $("m-profile-status"); st.textContent = "Saved";
      setTimeout(() => { st.textContent = ""; }, 1800);
    }
  }
  async function evolveMemory() {
    const btn = $("m-evolve");
    btn.disabled = true; btn.textContent = "Consolidating...";
    const data = await memPost("/api/memory/evolve", {});
    if (data) {
      applyMemoryPayload(data);
      const e = data.evolve || {};
      const note = $("m-change-note"); note.hidden = false;
      note.textContent = `Evolved: ${e.compressed || 0} compressed, ${e.decayed || 0} reweighted, ${e.kept || 0} kept.`;
    }
    btn.disabled = false; btn.textContent = "Consolidate memory now";
  }

  // Make every panel collapsible by clicking its header (state remembered).
  function setupCollapsibles() {
    document.querySelectorAll(".glass.panel").forEach((panel) => {
      const head = panel.firstElementChild;
      if (!head || !head.classList.contains("section-head")) return;
      const h2 = head.querySelector("h2");
      if (!h2 || h2.dataset.collapsible) return;
      h2.dataset.collapsible = "1";
      const chev = document.createElement("span");
      chev.className = "collapse-chev";
      h2.prepend(chev);
      h2.style.cursor = "pointer";
      const key = "collapse:" + h2.textContent.trim();
      const apply = (c) => { panel.classList.toggle("collapsed", c); chev.textContent = c ? "\u25B8" : "\u25BE"; };
      let collapsed = false;
      try { collapsed = localStorage.getItem(key) === "1"; } catch (e) { /* ignore */ }
      apply(collapsed);
      h2.addEventListener("click", () => {
        collapsed = !collapsed;
        apply(collapsed);
        try { localStorage.setItem(key, collapsed ? "1" : "0"); } catch (e) { /* ignore */ }
      });
    });
  }

  function init() {
    $("tab-resume").addEventListener("click", () => switchTab("resume"));
    $("tab-digest").addEventListener("click", () => switchTab("digest"));
    $("tab-memory").addEventListener("click", () => switchTab("memory"));
    setupCollapsibles();
    ["d-weekly-goals", "d-tasks", "d-longterm-goals", "d-schedule"].forEach(enableTabKey);
    $("m-ingest").addEventListener("click", ingestResume);
    $("m-resume-file").addEventListener("change", onMemResumeFile);
    $("m-apply").addEventListener("click", applyMemoryCommand);
    $("m-add-direct").addEventListener("click", addDirectMemory);
    $("m-profile-save").addEventListener("click", saveProfileBase);
    $("m-evolve").addEventListener("click", evolveMemory);
    $("d-save").addEventListener("click", () => saveConfig(false));
    $("d-add-update").addEventListener("click", addUpdate);
    $("d-update-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addUpdate(); }
    });
    $("d-preview").addEventListener("click", preview);
    $("d-send").addEventListener("click", sendNow);
    $("d-resend").addEventListener("click", resendNow);
    // persist toggles immediately so the scheduler reflects them
    $("d-enabled").addEventListener("change", () => saveConfig(true));
    $("d-offline").addEventListener("change", () => saveConfig(true));
    ["d-inc-schedule", "d-inc-calendar", "d-inc-trackers", "d-korean"].forEach((id) =>
      $(id).addEventListener("change", () => { saveConfig(true).then(loadStatus); }));
    $("d-korean-level").addEventListener("change", () => saveConfig(true));
    $("d-english-level").addEventListener("change", () => saveConfig(true));
    $("d-language").addEventListener("change", () => {
      applyLanguageUI();
      saveConfig(true).then(loadStatus);
    });
    $("d-capacity").addEventListener("change", () => saveConfig(true));
    // in-page sub-tab navigation
    document.querySelectorAll("#digest-subtabs .subtab").forEach((b) =>
      b.addEventListener("click", () => switchSub(b.dataset.sub)));
    let savedSub = "digest";
    try { savedSub = localStorage.getItem("digestSub") || "digest"; } catch (e) { /* ignore */ }
    switchSub(savedSub);
    // schedule
    $("d-parse").addEventListener("click", parseSchedule);
    $("d-push-cal").addEventListener("click", pushCalendar);
    // trackers
    $("d-tracker-save").addEventListener("click", addTracker);
    $("d-tracker-test").addEventListener("click", testTracker);
    // korean
    $("d-korean-preview").addEventListener("click", previewKorean);
    $("d-korean-place").addEventListener("click", setPlacement);
    $("d-reminder-add").addEventListener("click", addReminder);
    $("d-reminder-text").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addReminder(); }
    });
    // weekly tasks
    $("d-wt-derive").addEventListener("click", deriveTasks);
    $("d-wt-clear-done").addEventListener("click", clearDoneTasks);
    $("d-wt-clear-all").addEventListener("click", () => clearCategory("weekly_tasks", "all weekly tasks"));
    $("d-wt-addtoggle").addEventListener("click", () => {
      const row = $("d-wt-addrow");
      row.hidden = !row.hidden;
      $("d-wt-addtoggle").textContent = row.hidden ? "+ Add task" : "\u2212 Add task";
      if (!row.hidden) $("d-wt-input").focus();
    });
    $("d-wt-add").addEventListener("click", addTask);
    // clear / reset
    document.querySelectorAll("[data-clear]").forEach((b) =>
      b.addEventListener("click", () => clearCategory(b.dataset.clear, b.textContent.trim())));
    $("d-reset-all").addEventListener("click", () => clearCategory("all", "ALL content", true));
    // news / interests / replies
    $("d-news-enabled").addEventListener("change", () => saveNews());
    $("d-news-add").addEventListener("click", addNewsSource);
    $("d-news-save").addEventListener("click", () => saveNews(true));
    $("d-replies-process").addEventListener("click", processReplies);
    $("d-wt-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addTask(); }
    });

    // Restore the tab the user was last on; default to the Daily Digest landing page.
    let saved = "digest";
    try { saved = localStorage.getItem("activeTab") || "digest"; } catch (e) { /* ignore */ }
    if (!VIEWS.includes(saved)) saved = "digest";
    switchTab(saved);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
