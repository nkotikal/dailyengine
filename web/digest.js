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

  function switchMemorySub(which) {
    const tabs = document.querySelectorAll("#memory-subtabs .subtab");
    let valid = false;
    tabs.forEach((b) => { if (b.dataset.sub === which) valid = true; });
    if (!valid) which = "memories";
    tabs.forEach((b) => b.classList.toggle("active", b.dataset.sub === which));
    document.querySelectorAll("#view-memory .glass.panel[data-group]").forEach((p) => {
      p.hidden = p.dataset.group !== which;
    });
    // The grid wrapper for the memories cards should collapse on the Profile tab.
    const grid = document.querySelector("#view-memory .grid");
    if (grid) grid.hidden = which !== "memories";
    try { localStorage.setItem("memorySub", which); } catch (e) { /* ignore */ }
  }

  function applyLanguageUI() {
    const lang = ($("d-language") && $("d-language").value) || "korean";
    if ($("d-korean-opts")) $("d-korean-opts").hidden = lang !== "korean";
    if ($("d-english-opts")) $("d-english-opts").hidden = lang !== "english";
    // Grading (own example sentences) is a Korean-track feature.
    if ($("d-korean-grade-box")) $("d-korean-grade-box").hidden = lang !== "korean";
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
      checkins_enabled: $("d-checkins") ? $("d-checkins").checked : false,
      checkin_times: $("d-checkin-times")
        ? $("d-checkin-times").value.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      checkin_scope: ($("d-checkin-scope") && $("d-checkin-scope").value) || "up_to_now",
      checkin_show_score: $("d-checkin-score") ? $("d-checkin-score").checked : true,
      checkin_show_later: $("d-checkin-later") ? $("d-checkin-later").checked : true,
      checkin_show_hint: $("d-checkin-hint") ? $("d-checkin-hint").checked : true,
      eod_recap_enabled: $("d-recap") ? $("d-recap").checked : false,
      eod_recap_time: ($("d-recap-time") && $("d-recap-time").value) || "21:00",
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
    if ($("d-checkins")) $("d-checkins").checked = !!cfg.checkins_enabled;
    if ($("d-checkin-times")) $("d-checkin-times").value = (cfg.checkin_times || []).join(", ");
    if ($("d-checkin-scope")) $("d-checkin-scope").value = cfg.checkin_scope || "up_to_now";
    if ($("d-checkin-score")) $("d-checkin-score").checked = cfg.checkin_show_score !== false;
    if ($("d-checkin-later")) $("d-checkin-later").checked = cfg.checkin_show_later !== false;
    if ($("d-checkin-hint")) $("d-checkin-hint").checked = cfg.checkin_show_hint !== false;
    if ($("d-recap")) $("d-recap").checked = !!cfg.eod_recap_enabled;
    if ($("d-recap-time")) $("d-recap-time").value = cfg.eod_recap_time || "21:00";
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
      renderKoreanScores(s.korean);
      renderAccountability(s.accountability);
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
           $("d-wt-derive"), 'Add from "Goals this week"');
  }
  async function refreshTasks() {
    const has = (($("d-weekly-goals").value) || "").trim();
    if (!has) { wtError("Put this week's task suite in \"Goals this week\" first."); return; }
    if (!confirm("Replace ALL current weekly tasks with a fresh set from \"Goals this week\"? "
      + "Completed and in-progress tasks will be cleared. (Reminders are not affected.)")) return;
    const data = await wtPost("/api/digest/tasks/derive",
      { weekly_text: $("d-weekly-goals").value, replace: true },
      $("d-wt-refresh"), "Refresh for new week (replace)");
    if (data && data.ok) {
      if (data.error_note) { wtError(data.error_note); return; }
      const st = $("d-wt-error");
      st.hidden = false; st.style.color = "var(--text-soft)";
      st.textContent = `Refreshed: replaced ${data.removed} old task(s) with ${data.added} new.`;
      setTimeout(() => { st.hidden = true; st.style.color = ""; }, 4000);
    }
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
    const forWhen = ($("d-schedule-for") && $("d-schedule-for").value) || "today";
    setBusy(btn, true, "Parse & save");
    try {
      const r = await fetch("/api/digest/schedule", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw: $("d-schedule").value, for: forWhen }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Parse failed."); return; }
      renderParsed(data.parsed);
      const note = $("d-cal-note");
      if (note && data.for_date) {
        const label = data.for_date === new Date().toISOString().slice(0, 10) ? "today" : data.for_date;
        note.innerHTML = `Saved for <strong>${label}</strong> \u00b7 ${(data.counts && data.counts.tasks) || 0} task(s).`;
      }
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
      const wk = (lang === "korean" && k) ? k.weekly : null;
      let wkHtml = "";
      if (wk && wk.total) {
        const wpct = Math.round(100 * wk.completed / wk.total);
        const rem = (wk.remaining || []).map((w) => w.korean).slice(0, 15).join(", ");
        wkHtml = `
        <div class="d-prog-row"><span>This week: ${escapeHtml(wk.theme || "theme")}</span><span>${wk.completed}/${wk.total} completed</span></div>
        <div class="d-prog-bar"><span style="width:${wpct}%"></span></div>
        <div class="d-prog-meta">${wk.done ? "\u2713 Week complete!" : ("Still to complete: " + escapeHtml(rem || "\u2014"))}</div>`;
      }
      wrap.innerHTML = `
        <div class="d-prog-row"><span>Grammar syllabus</span><span>${prog.grammar_done}/${prog.grammar_total}</span></div>
        <div class="d-prog-bar"><span style="width:${gpct}%"></span></div>
        ${wkHtml}
        <div class="d-prog-meta">${prog.tracked_items} grammar items in spaced repetition · ${prog.reviews_due} due today · complete words by replying with your own example sentence</div>`;
    } else {
      wrap.innerHTML = "";
    }
  }

  // Persistent scorekeeping for graded practice sentences (Korean track).
  function renderKoreanScores(k) {
    const box = $("d-korean-scores");
    if (!box) return;
    const lang = (k && k.language) || "korean";
    const ps = (lang === "korean" && k) ? k.practice : null;
    if (!ps || !ps.total) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    const pass = ps.pass_threshold || 70;
    const chip = (label, value, sub) =>
      `<div class="d-score-chip"><div class="d-score-val">${value}</div>` +
      `<div class="d-score-lbl">${escapeHtml(label)}</div>` +
      (sub ? `<div class="d-score-sub">${escapeHtml(sub)}</div>` : "") + `</div>`;
    const streakTxt = ps.streak ? `${ps.streak}\u{1F525}` : "0";
    let html = `<div class="d-k-heading">Practice scoreboard</div>
      <div class="d-score-chips">
        ${chip("Avg score", ps.avg, `${ps.passed}/${ps.total} passed`)}
        ${chip("Pass rate", ps.pass_rate + "%", `bar to pass: ${pass}`)}
        ${chip("This week", ps.week_avg, `${ps.week_passed}/${ps.week_total} passed`)}
        ${chip("Streak", streakTxt, "days passing")}
      </div>`;
    if (ps.recent && ps.recent.length) {
      html += `<div class="d-k-subheading">Recent sentences</div>`;
      html += `<div class="d-score-list">` + ps.recent.map((r) => {
        const passed = (r.score || 0) >= pass;
        const cls = passed ? "pass" : "fail";
        const showCorrected = r.corrected && r.corrected.trim() &&
          r.corrected.trim() !== (r.sentence || "").trim();
        return `<div class="d-score-item ${cls}">
          <div class="d-score-item-top">
            <span class="d-score-sent">${escapeHtml(r.sentence || "")}</span>
            <span class="d-score-badge ${cls}">${r.score}</span>
          </div>
          ${showCorrected ? `<div class="d-score-fix"><strong>Better:</strong> ${escapeHtml(r.corrected)}</div>` : ""}
          ${r.feedback ? `<div class="d-score-fb">${escapeHtml(r.feedback)}</div>` : ""}
          <div class="d-score-date">${escapeHtml(r.date || "")}${r.word ? " \u00b7 practiced " + escapeHtml(r.word) : ""}</div>
        </div>`;
      }).join("") + `</div>`;
    }
    box.innerHTML = html;
  }

  // Accountability scoreboard: today's score, this week, weekly trend, leaderboard.
  function renderAccountability(a) {
    const pill = $("d-score-pill");
    const board = $("d-score-board");
    if (!a) { if (board) { board.hidden = true; board.innerHTML = ""; } return; }
    if (pill) {
      const on = a.checkins_enabled || a.eod_recap_enabled;
      pill.textContent = on ? `${(a.today && a.today.total) || 0} pts today` : "off";
      pill.className = on ? "pill good" : "pill ghost";
    }
    if (!board) return;
    const today = a.today || {};
    const week = a.week || {};
    const chip = (val, lbl) =>
      `<div class="d-score-chip"><div class="d-score-val">${val}</div>` +
      `<div class="d-score-lbl">${escapeHtml(lbl)}</div></div>`;
    let html = `<div class="d-k-heading">Score</div>
      <div class="d-score-chips">
        ${chip((today.total || 0), "points today")}
        ${chip(`${today.done || 0}/${today.count || 0}`, "tasks done")}
        ${chip((week.total || 0), "this week")}
        ${chip(`${today.pct || 0}%`, "of plan")}
      </div>`;

    const weeks = a.weeks || [];
    if (weeks.length) {
      const max = Math.max(1, ...weeks.map((w) => w.total || 0));
      html += `<div class="d-k-subheading">Weekly trend</div><div class="d-trend">` +
        weeks.map((w) => {
          const h = Math.round(6 + 46 * ((w.total || 0) / max));
          const label = (w.week_start || "").slice(5);
          return `<div class="d-trend-col" title="${escapeHtml(label)}: ${w.total || 0} pts">` +
            `<div class="d-trend-bar" style="height:${h}px"></div>` +
            `<div class="d-trend-x">${escapeHtml(label)}</div></div>`;
        }).join("") + `</div>`;
    }

    const lb = a.leaderboard || [];
    if (lb.length) {
      html += `<div class="d-k-subheading">Leaderboard (this week)</div><div class="d-lb">` +
        lb.map((r) => `<div class="d-lb-row">
          <span class="d-lb-rank">#${r.rank}</span>
          <span class="d-lb-name">${escapeHtml(r.name)}</span>
          <span class="d-lb-pts">${r.points} pts</span></div>`).join("") + `</div>`;
    }
    board.hidden = false;
    board.innerHTML = html;
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

  async function gradeKorean() {
    showError("");
    const raw = ($("d-korean-practice") && $("d-korean-practice").value || "").trim();
    if (!raw) { showError("Write one or more Korean sentences to grade."); return; }
    const btn = $("d-korean-grade");
    setBusy(btn, true, "Grade my sentences");
    try {
      const r = await fetch("/api/digest/korean/grade", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentences: raw }),
      });
      const data = await r.json();
      if (!data.ok) { showError(data.error || "Grading failed."); return; }
      renderGradedResults(data.results || []);
      loadStatus();  // refresh the scoreboard from updated practice stats
    } catch (e) { showError("Network error: " + e.message); }
    finally { setBusy(btn, false, "Grade my sentences"); }
  }

  function renderGradedResults(results) {
    const box = $("d-korean-graded");
    if (!box) return;
    if (!results.length) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    const pass = 70;
    box.innerHTML = results.map((r) => {
      const passed = (r.score || 0) >= pass;
      const cls = passed ? "pass" : "fail";
      const showFix = r.corrected && r.corrected.trim() &&
        r.corrected.trim() !== (r.sentence || "").trim();
      return `<div class="d-score-item ${cls}">
        <div class="d-score-item-top">
          <span class="d-score-sent">${escapeHtml(r.sentence || "")}</span>
          <span class="d-score-badge ${cls}">${r.score}</span>
        </div>
        ${showFix ? `<div class="d-score-fix"><strong>Better:</strong> ${escapeHtml(r.corrected)}</div>` : ""}
        ${r.feedback ? `<div class="d-score-fb">${escapeHtml(r.feedback)}</div>` : ""}
      </div>`;
    }).join("");
    if ($("d-korean-practice")) $("d-korean-practice").value = "";
  }

  function _reportNote(html, cls) {
    const note = $("d-report-note");
    if (!note) return;
    note.hidden = false;
    note.innerHTML = `<div class="d-report-conf ${cls || "ok"}">${html}</div>`;
  }

  function renderReportResult(data) {
    const sc = data.score || {};
    if (data.completed_count === 0) {
      _reportNote(`Parsed <strong>${data.parsed_tasks}</strong> line(s), but none were marked with <code>#</code>. Start a line with <code>#</code> to log it as completed.`, "warn");
      return;
    }
    const ICON = { done: "\u2705", already_done: "\u2705", added: "\u2795" };
    const TAIL = { done: "", already_done: " (was already done)", added: " \u2014 logged (wasn't in the plan)" };
    const rows = (data.items || []).map((it) =>
      `<div style="padding:3px 0;font-size:13.5px;">${ICON[it.status] || "\u2022"} ${escapeHtml(it.text)}` +
      `<span style="color:var(--text-faint);">${TAIL[it.status] || ""}</span></div>`
    ).join("");
    const bits = [`<strong>${data.matched}</strong> matched`];
    if (data.added) bits.push(`<strong>${data.added}</strong> added`);
    if (data.newly_done) bits.push(`<strong>${data.newly_done}</strong> newly done`);
    const summary = `Logged ${bits.join(" \u00b7 ")}` +
      (sc.total != null ? ` \u00b7 today <strong>${sc.done}/${sc.count}</strong> \u00b7 ${sc.total} pts` : "");
    _reportNote(`<div style="font-weight:600;margin-bottom:6px;">\u2713 ${summary}</div>${rows}`, "ok");
  }

  async function submitReport() {
    showError("");
    const raw = ($("d-report") && $("d-report").value || "").trim();
    if (!raw) { _reportNote("Paste your day first (use <code>#</code> to mark completed tasks).", "warn"); return; }
    const btn = $("d-report-submit");
    setBusy(btn, true, "Log completed");
    _reportNote("Logging\u2026", "ok");
    try {
      const r = await fetch("/api/digest/report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw }),
      });
      let data = null;
      try { data = await r.json(); } catch (e) { data = null; }
      if (!r.ok || !data) {
        _reportNote(`Couldn't reach the report endpoint (HTTP ${r.status}). Restart the server so the new route loads, then hard-refresh this page.`, "warn");
        return;
      }
      if (!data.ok) { _reportNote(escapeHtml(data.error || "Could not apply report."), "warn"); return; }
      renderReportResult(data);
      loadStatus();
    } catch (e) {
      _reportNote("Network error: " + escapeHtml(e.message) + ". Is the server running?", "warn");
    } finally { setBusy(btn, false, "Log completed"); }
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
    const wp = lesson.weekly_progress;
    if (wp && wp.theme) {
      html += `<div class="d-k-card" style="border-color:rgba(124,155,255,0.4)">
        <div class="d-k-label" style="margin:0 0 4px">Weekly theme: ${escapeHtml(wp.theme)} · ${wp.completed}/${wp.total} done</div>
        ${lesson.challenge ? `<div class="d-k-en">${escapeHtml(lesson.challenge)}</div>` : ""}
      </div>`;
    }
    if (lesson.vocab && lesson.vocab.length) {
      html += `<div class="d-k-section"><div class="d-k-heading">Today's words <span class="d-k-count">${lesson.vocab.length}</span></div>`;
      html += lesson.vocab.map((v) => `<div class="d-k-card vocab">
        <div class="d-k-term"><span class="d-k-ko">${escapeHtml(v.korean)}</span>${v.romanization ? `<span class="d-k-rom">${escapeHtml(v.romanization)}</span>` : ""}${v.pos ? ` <em class="d-k-pos">${escapeHtml(v.pos)}</em>` : ""}</div>
        <div class="d-k-en">${escapeHtml(v.english)}</div>
        ${v.example_ko ? `<div class="d-k-ex"><span class="d-k-ex-ko">${escapeHtml(v.example_ko)}</span><span class="d-k-ex-en">${escapeHtml(v.example_en)}</span></div>` : ""}
      </div>`).join("") + `</div>`;
    }
    if (lesson.grammar && lesson.grammar.length) {
      html += `<div class="d-k-section"><div class="d-k-heading">Grammar</div>`;
      html += lesson.grammar.map((g) => `<div class="d-k-card grammar">
        <div class="d-k-term"><span class="d-k-ko">${escapeHtml(g.point)}</span></div>
        <div class="d-k-en">${escapeHtml(g.english)}</div>
        ${g.form ? `<div class="d-k-form"><strong>Form:</strong> ${escapeHtml(g.form)}</div>` : ""}
        ${g.example_ko ? `<div class="d-k-ex"><span class="d-k-ex-ko">${escapeHtml(g.example_ko)}</span><span class="d-k-ex-en">${escapeHtml(g.example_en)}</span></div>` : ""}
      </div>`).join("") + `</div>`;
    }
    if (lesson.review && lesson.review.length) {
      html += `<div class="d-k-section"><div class="d-k-heading">Review <span class="d-k-count">spaced repetition</span></div>`;
      html += lesson.review.map((r) => `<div class="d-k-card review">
        <div class="d-k-term"><span class="d-k-ko">${escapeHtml(r.item)}</span></div>
        <div class="d-k-en">${escapeHtml(r.prompt)} <strong>${escapeHtml(r.answer)}</strong></div>
        ${r.example_ko ? `<div class="d-k-ex"><span class="d-k-ex-ko">${escapeHtml(r.example_ko)}</span>${r.example_en ? `<span class="d-k-ex-en">${escapeHtml(r.example_en)}</span>` : ""}</div>` : ""}
      </div>`).join("") + `</div>`;
    }
    if (lesson.tip) html += `<div class="d-k-tip">💡 <strong>Tip:</strong> ${escapeHtml(lesson.tip)}</div>`;
    if (lesson.culture) html += `<div class="d-k-tip culture">🏛️ <strong>Culture:</strong> ${escapeHtml(lesson.culture)}</div>`;
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
    const btn = $("d-send");
    setBusy(btn, true, "Send now");
    try {
      // Persist the schedule you may have just typed so it's in the sent digest.
      const raw = $("d-schedule") ? $("d-schedule").value : "";
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

  // ============================ MEMORY ============================
  let memories = [];
  let memCategories = [];
  let memFilter = "all";
  let memSort = "importance";
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

    const recent = (m) => (m.updated_at || m.created_at || "");
    const shown = memories
      .filter((m) => memFilter === "all" || m.category === memFilter)
      .sort((a, b) => memSort === "recent"
        ? recent(b).localeCompare(recent(a))
        : (b.importance || 0) - (a.importance || 0));
    const list = $("m-list");
    if (!shown.length) { list.innerHTML = `<div class="m-empty">No memories yet. Upload a resume or tell it about yourself.</div>`; return; }
    const SOURCE_COLOR = {
      reflection: "var(--ok)", compressed: "var(--accent)", nl: "#c08cff",
      resume: "var(--text-faint)", manual: "var(--text-faint)",
    };
    const todayStr = new Date().toISOString().slice(0, 10);
    const daysAgo = (s) => {
      const d = (s || "").slice(0, 10);
      if (!d) return 999;
      return Math.round((Date.parse(todayStr) - Date.parse(d)) / 86400000);
    };
    list.innerHTML = shown.map((m) => {
      const imp = m.importance == null ? 60 : m.importance;
      const impColor = imp >= 66 ? "var(--ok)" : (imp >= 33 ? "var(--warn)" : "var(--text-faint)");
      const src = m.source || "manual";
      const srcColor = SOURCE_COLOR[src] || "var(--text-faint)";
      const isNew = daysAgo(m.created_at) <= 3;
      const isFresh = daysAgo(recent(m)) <= 3;
      const newTag = isNew ? `<span class="m-new">NEW</span>` : "";
      return `
      <div class="m-item${isFresh ? " m-item-fresh" : ""}">
        <div class="m-item-body">
          <div class="m-item-text" data-id="${m.id}">${newTag}${escapeHtml(m.text)}</div>
          <div class="m-item-meta">
            <span class="m-cat" data-id="${m.id}" title="Click to change category">${escapeHtml(m.category)}</span>
            <span class="m-src" style="color:${srcColor}" title="How this memory was created">${escapeHtml(src)}</span>
            <span class="m-imp" title="Importance"><span style="color:${impColor}">●</span> ${imp}</span>
            <span class="m-time" title="Created ${escapeHtml((m.created_at||'').slice(0,10))} · updated ${escapeHtml((m.updated_at||'').slice(0,10))}">${escapeHtml(recent(m).slice(0, 10))}</span>
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
    $("m-sort").querySelectorAll(".m-sort-btn").forEach((b) =>
      b.addEventListener("click", () => {
        memSort = b.dataset.sort;
        $("m-sort").querySelectorAll(".m-sort-btn").forEach((x) =>
          x.classList.toggle("active", x === b));
        renderMemory();
      }));
    $("d-save").addEventListener("click", () => saveConfig(false));
    $("d-add-update").addEventListener("click", addUpdate);
    $("d-update-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addUpdate(); }
    });
    $("d-preview").addEventListener("click", preview);
    $("d-send").addEventListener("click", sendNow);
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
    // accountability (check-ins + recap)
    ["d-checkins", "d-recap"].forEach((id) => {
      if ($(id)) $(id).addEventListener("change", () => { saveConfig(true).then(loadStatus); });
    });
    ["d-checkin-times", "d-recap-time", "d-checkin-scope", "d-checkin-score",
     "d-checkin-later", "d-checkin-hint"].forEach((id) => {
      if ($(id)) $(id).addEventListener("change", () => saveConfig(true));
    });
    // in-page sub-tab navigation
    document.querySelectorAll("#digest-subtabs .subtab").forEach((b) =>
      b.addEventListener("click", () => switchSub(b.dataset.sub)));
    let savedSub = "digest";
    try { savedSub = localStorage.getItem("digestSub") || "digest"; } catch (e) { /* ignore */ }
    switchSub(savedSub);
    // memory sub-tabs (Profile vs. growing memories)
    document.querySelectorAll("#memory-subtabs .subtab").forEach((b) =>
      b.addEventListener("click", () => switchMemorySub(b.dataset.sub)));
    let savedMemSub = "memories";
    try { savedMemSub = localStorage.getItem("memorySub") || "memories"; } catch (e) { /* ignore */ }
    switchMemorySub(savedMemSub);
    // schedule
    if ($("d-schedule-for")) {
      // Evening saves are almost always for the next morning.
      $("d-schedule-for").value = new Date().getHours() >= 18 ? "tomorrow" : "today";
    }
    $("d-parse").addEventListener("click", parseSchedule);
    $("d-push-cal").addEventListener("click", pushCalendar);
    // trackers
    $("d-tracker-save").addEventListener("click", addTracker);
    $("d-tracker-test").addEventListener("click", testTracker);
    // korean
    $("d-korean-preview").addEventListener("click", previewKorean);
    if ($("d-korean-grade")) $("d-korean-grade").addEventListener("click", gradeKorean);
    if ($("d-report-submit")) $("d-report-submit").addEventListener("click", submitReport);
    $("d-korean-place").addEventListener("click", setPlacement);
    $("d-reminder-add").addEventListener("click", addReminder);
    $("d-reminder-text").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addReminder(); }
    });
    // weekly tasks
    $("d-wt-derive").addEventListener("click", deriveTasks);
    $("d-wt-refresh").addEventListener("click", refreshTasks);
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
