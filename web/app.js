"use strict";

const $ = (id) => document.getElementById(id);

const SAMPLE_PROFILE = {
  contact: {
    name: "Jordan A. Rivera",
    email: "jordan.rivera@example.com",
    phone: "+1 555-0142",
    linkedin: "linkedin.com/in/jordan-rivera",
    github: "github.com/jordanrivera",
  },
  education: [
    { institution: "State University", location: "Austin, TX",
      degree: "B.S. in Computer Science", gpa: "3.8/4.0", dates: "Aug 2018 -- May 2022" },
  ],
  skills: {
    Languages: ["Python", "TypeScript", "Go", "SQL", "Java", "C++"],
    Frameworks: ["React", "Node.js", "Django", "FastAPI", "Spring Boot"],
    "Cloud & DevOps": ["AWS", "Docker", "Kubernetes", "Terraform", "CI/CD"],
    Data: ["PostgreSQL", "Redis", "Kafka", "Spark", "Snowflake"],
  },
  experience: [
    { company: "Cloudwave Systems", location: "Remote", role: "Senior Software Engineer",
      dates: "Jun 2022 -- Present", bullets: [
        "Architected a Python & FastAPI microservice on AWS handling 12M requests/day, cutting p95 latency by 38%.",
        "Led migration of a monolith to Kubernetes with Terraform-managed infrastructure, reducing deploy time from 45 min to 6 min.",
        "Built a Kafka-based event pipeline feeding Snowflake, enabling real-time analytics for 200+ internal users.",
        "Mentored 4 engineers and introduced CI/CD quality gates that dropped production incidents by 25%.",
        "Optimized PostgreSQL queries and Redis caching, saving an estimated $90k/year in compute costs.",
      ] },
    { company: "Brightline Apps", location: "Austin, TX", role: "Software Engineer",
      dates: "Jul 2020 -- May 2022", bullets: [
        "Developed React & TypeScript front-end features used by 50k+ monthly active users.",
        "Implemented a Django REST API and integrated Stripe billing with 99.9% uptime.",
        "Wrote automated tests raising coverage from 40% to 85% across the core service.",
        "Collaborated with design to ship an accessibility overhaul meeting WCAG 2.1 AA.",
      ] },
  ],
  projects: [
    { title: "OpenMetrics Dashboard", tech: ["Go", "React", "Prometheus", "Docker"], dates: "2023",
      bullets: [
        "Built an open-source observability dashboard with 1.2k GitHub stars.",
        "Implemented a Go collector exporting 60+ Prometheus metrics with <2% overhead.",
      ] },
    { title: "ResumeForge", tech: ["Python", "LaTeX", "FastAPI"], dates: "2022",
      bullets: [
        "Created a deterministic JSON-to-LaTeX resume generator with ATS-aware formatting.",
        "Added a one-page auto-fit compiler loop using pdflatex.",
      ] },
  ],
};

const SAMPLE_JD = `Senior Backend Engineer

We are looking for a backend engineer experienced with Python and FastAPI to
build and operate microservices on AWS. You will work with Kubernetes, Docker,
and Terraform to manage infrastructure as code, and design event pipelines with
Kafka feeding our Snowflake warehouse. Strong PostgreSQL and Redis skills are
required. Experience with CI/CD and Go is a plus.`;

let profileStored = false;
let pendingPdfBase64 = null;   // base64 of an uploaded PDF, if any
let pendingPdfName = null;

function chip(label, value, state) {
  const cls = state ? ` ${state}` : "";
  return `<span class="chip${cls}"><span class="dot"></span>${label}: <strong>${value}</strong></span>`;
}

let profileName = "";

async function loadStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    profileStored = s.profile_stored;
    profileName = s.profile_name || "";

    const host = s.gateway.replace(/^https?:\/\//, "").split("/")[0];
    const profileChip = s.profile_stored ? (profileName || "stored") : "needed";
    const chips = [
      chip("Profile", profileChip, s.profile_stored ? "good" : "bad"),
      chip("Model", s.model, "good"),
      chip("Gateway", host, "good"),
      chip("API key", s.has_key ? "configured" : "missing", s.has_key ? "good" : "bad"),
      chip("LaTeX", s.pdflatex ? "ready" : "missing", s.pdflatex ? "good" : "bad"),
    ];
    $("status-chips").innerHTML = chips.join("");

    const pill = $("profile-pill");
    const clearBtn = $("clear-profile");
    if (s.profile_stored) {
      pill.textContent = profileName ? `Saved: ${profileName}` : "Saved profile in use";
      pill.className = "pill good";
      $("profile-hint").innerHTML = profileName
        ? `Using saved profile: <strong>${escapeHtml(profileName)}</strong>. ` +
          `If that isn't you, click <strong>Clear saved profile</strong>, then add yours below.`
        : "Your saved profile is used automatically - paste a full resume below to replace it.";
      clearBtn.hidden = false;
      $("profile-toggle").setAttribute("aria-expanded", "false");
      $("profile-wrap").hidden = true;
    } else {
      pill.textContent = "Profile required";
      pill.className = "pill need";
      $("profile-hint").textContent = "No profile saved yet. Upload your resume PDF, or paste your full resume / a profile JSON to get started (saved for next time).";
      clearBtn.hidden = true;
      $("profile-toggle").setAttribute("aria-expanded", "true");
      $("profile-wrap").hidden = false;
      $("profile-toggle-label").textContent = "Your resume / profile";
    }
  } catch (e) {
    $("status-chips").innerHTML = chip("Server", "unreachable", "bad");
  }
}

async function clearProfile() {
  if (!confirm("Delete the saved profile and stored context? You'll need to add your resume again.")) return;
  showError("");
  try {
    await fetch("/api/reset", { method: "POST" });
    $("profile").value = "";
    clearFile();
    $("result-live").hidden = true;
    $("result-empty").hidden = false;
    $("gaps-panel").hidden = true;
    await loadStatus();
    loadSavedProfile();
    if ($("profile-wrap").hidden) toggleProfile();
  } catch (e) {
    showError("Could not clear the saved profile: " + e.message);
  }
}

function toggleProfile() {
  const btn = $("profile-toggle");
  const open = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!open));
  $("profile-wrap").hidden = open;
}

function b64ToBlob(b64, type) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type });
}

function setBusy(busy, fromGaps) {
  const btn = fromGaps ? $("regenerate") : $("generate");
  const label = fromGaps ? "Add details & regenerate" : "Generate resume";
  $("generate").disabled = busy;
  $("regenerate").disabled = busy;
  btn.querySelector(".btn-label").textContent = busy ? "Optimizing..." : label;
  btn.querySelector(".spinner").hidden = !busy;
}

function showError(msg) {
  const el = $("error");
  el.textContent = msg;
  el.hidden = !msg;
}

// Some embedded browsers (e.g. the in-editor preview) swallow Ctrl/Cmd+V into
// form fields. This reads the clipboard via the async Clipboard API and inserts
// the text at the cursor, giving a reliable paste path everywhere.
async function pasteFromClipboard(targetId) {
  const el = $(targetId);
  if (!el) return;
  showError("");
  try {
    const text = await navigator.clipboard.readText();
    if (!text) { el.focus(); return; }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    el.value = el.value.slice(0, start) + text + el.value.slice(end);
    const pos = start + text.length;
    el.focus();
    el.setSelectionRange(pos, pos);
  } catch (e) {
    el.focus();
    showError(
      "Couldn't read the clipboard here. Click the field and press Ctrl+V " +
      "(Cmd+V on Mac), or open this app in a regular browser at this address."
    );
  }
}

let lastPdfUrl = null;
let lastTexUrl = null;

async function generate(opts) {
  opts = opts || {};
  showError("");
  const jd = $("jd").value.trim();
  if (!jd) { showError("Please paste a job description."); return; }

  const profileText = $("profile").value.trim();
  const hasInput = profileText || pendingPdfBase64;
  if (!profileStored && !hasInput) {
    showError("On the first run, add your resume: upload a PDF, paste resume text, or paste a profile JSON.");
    if ($("profile-wrap").hidden) toggleProfile();
    return;
  }

  const payload = {
    jd_text: jd,
    deterministic: $("deterministic").checked,
    model: $("model").value || null,
  };
  // Only resend resume text when seeding or the user explicitly opened the profile
  // panel to update it. Otherwise regeneration continues from the saved draft.
  const profileOpen = $("profile-toggle").getAttribute("aria-expanded") === "true";
  if (profileText && (!profileStored || profileOpen || pendingPdfBase64)) {
    payload.context_text = profileText;
  }
  if (pendingPdfBase64) payload.resume_pdf_base64 = pendingPdfBase64;
  if (opts.notes) payload.notes = opts.notes;

  setBusy(true, opts.fromGaps);
  try {
    const r = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!data.ok) { showError(data.error || "Generation failed."); return; }

    updatePdfPreview(data.pdf_base64, data.tex);
    $("tex-editor").value = data.tex;
    $("tex-editor-wrap").hidden = true;
    $("toggle-tex").textContent = "Edit LaTeX";

    const mode = data.used_llm ? "AI-optimized" : "offline";
    const who = data.profile_name ? ` (${data.profile_name})` : "";
    const srcMap = {
      parsed: "parsed from your resume" + who,
      provided: "from your input" + who,
      stored: "saved profile" + who,
      optimized: "continuing prior draft" + who,
    };
    const src = srcMap[data.profile_source] || data.profile_source;
    const ctx = data.context_used ? " · full context" : "";
    const meta = $("result-meta");
    meta.hidden = false;
    meta.textContent = `${data.pages} page · ${mode} · ${src}${ctx} · ${data.font_pt}pt`;
    if (data.warnings && data.warnings.length) showError(data.warnings.join(" "));

    const summaryBox = $("summary-box");
    const summaryText = $("summary-text");
    if (data.summary) {
      summaryText.textContent = data.summary;
      summaryBox.hidden = false;
    } else {
      summaryText.textContent = "";
      summaryBox.hidden = true;
    }

    // profile is now stored; clear the textarea so regenerate won't resend it
    if (data.profile_source === "parsed" || data.profile_source === "provided") {
      $("profile").value = "";
    }

    // a freshly uploaded PDF has now been parsed + stored; clear the pending file
    clearFile();

    $("result-empty").hidden = true;
    $("result-live").hidden = false;

    renderGaps(data.gaps || []);

    // notes were just persisted; clear the gap inputs for the next pass
    if (opts.fromGaps) clearGapInputs();

    // refresh status (profile may now be stored)
    loadStatus();
    loadSavedProfile();
  } catch (e) {
    showError("Network error: " + e.message);
  } finally {
    setBusy(false, opts.fromGaps);
  }
}

function gapTier(p) {
  if (p >= 80) return "must";
  if (p >= 50) return "pref";
  return "nice";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function renderGaps(gaps) {
  const panel = $("gaps-panel");
  const list = $("gaps-list");
  const count = $("gaps-count");
  if (!gaps.length) {
    list.innerHTML = `<p class="gaps-clear">No gaps - your resume covers this job description well.</p>`;
    count.hidden = true;
    panel.hidden = false;
    $("gaps-notes").parentElement.hidden = false;
    return;
  }
  count.hidden = false;
  count.textContent = `${gaps.length} to consider`;
  list.innerHTML = gaps.map((g, i) => {
    const tier = gapTier(g.importance);
    return `
    <div class="gap-item tier-${tier}">
      <div class="gap-bar-wrap" title="${g.importance}% important to this role">
        <div class="gap-pct">${g.importance}%</div>
        <div class="gap-bar"><span style="width:${g.importance}%"></span></div>
      </div>
      <div class="gap-body">
        <div class="gap-req">${escapeHtml(g.requirement)}</div>
        ${g.reason ? `<div class="gap-reason">${escapeHtml(g.reason)}</div>` : ""}
        ${g.suggestion ? `<div class="gap-suggestion">${escapeHtml(g.suggestion)}</div>` : ""}
        <input type="text" class="field gap-input" data-req="${escapeHtml(g.requirement)}"
          placeholder="Your relevant experience (leave blank if it doesn't apply)" />
      </div>
    </div>`;
  }).join("");
  panel.hidden = false;
  $("gaps-notes").parentElement.hidden = false;
}

function collectGapNotes() {
  const parts = [];
  document.querySelectorAll(".gap-input").forEach((inp) => {
    const v = inp.value.trim();
    if (v) parts.push(`${inp.dataset.req}: ${v}`);
  });
  const extra = $("gaps-notes").value.trim();
  if (extra) parts.push(extra);
  return parts.join("\n");
}

function clearGapInputs() {
  document.querySelectorAll(".gap-input").forEach((inp) => { inp.value = ""; });
  $("gaps-notes").value = "";
}

async function regenerateWithGaps() {
  const notes = collectGapNotes();
  if (!notes) {
    showError("Add at least one detail above (or extra notes) before regenerating.");
    return;
  }
  await generate({ notes, fromGaps: true });
}

function updatePdfPreview(pdfBase64, tex) {
  if (lastPdfUrl) URL.revokeObjectURL(lastPdfUrl);
  if (lastTexUrl) URL.revokeObjectURL(lastTexUrl);
  const pdfBlob = b64ToBlob(pdfBase64, "application/pdf");
  lastPdfUrl = URL.createObjectURL(pdfBlob);
  const texBlob = new Blob([tex], { type: "text/plain" });
  lastTexUrl = URL.createObjectURL(texBlob);
  $("pdf-frame").src = lastPdfUrl;
  $("download-pdf").href = lastPdfUrl;
  $("download-tex").href = lastTexUrl;
}

async function recompileTex() {
  showError("");
  const tex = $("tex-editor").value;
  if (!tex.trim()) {
    showError("LaTeX source is empty.");
    return;
  }
  const btn = $("recompile-tex");
  btn.disabled = true;
  btn.querySelector(".btn-label").textContent = "Compiling...";
  btn.querySelector(".spinner").hidden = false;
  try {
    const r = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tex }),
    });
    const data = await r.json();
    if (!data.ok) {
      showError(data.error || "LaTeX compilation failed.");
      return;
    }
    updatePdfPreview(data.pdf_base64, data.tex);
    $("tex-editor").value = data.tex;
    const meta = $("result-meta");
    meta.hidden = false;
    meta.textContent = `${data.pages ?? "?"} page · manual LaTeX edit`;
    if (data.warnings && data.warnings.length) showError(data.warnings.join(" "));
    $("result-empty").hidden = true;
    $("result-live").hidden = false;
  } catch (e) {
    showError("Network error: " + e.message);
  } finally {
    btn.disabled = false;
    btn.querySelector(".btn-label").textContent = "Recompile PDF";
    btn.querySelector(".spinner").hidden = true;
  }
}

function fileToBase64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1]);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}
function fileToText(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result));
    r.onerror = rej;
    r.readAsText(file);
  });
}
function showFileChip(name) {
  const chip = $("file-chip");
  chip.hidden = false;
  chip.innerHTML = `${name} <span class="chip-x" title="Remove">×</span>`;
  chip.querySelector(".chip-x").addEventListener("click", clearFile);
}
function clearFile() {
  pendingPdfBase64 = null;
  pendingPdfName = null;
  $("file-chip").hidden = true;
  $("file-chip").innerHTML = "";
  $("resume-file").value = "";
}
async function onFile(e) {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  showError("");
  const name = f.name.toLowerCase();
  try {
    if (name.endsWith(".pdf")) {
      pendingPdfBase64 = await fileToBase64(f);
      pendingPdfName = f.name;
      showFileChip(f.name);
    } else {
      $("profile").value = await fileToText(f);
      pendingPdfBase64 = null;
      pendingPdfName = null;
      showFileChip(f.name);
    }
  } catch (err) {
    showError("Could not read that file.");
  }
}

// ---- saved profile: view / edit / history ----
let spOriginal = "";

async function loadSavedProfile() {
  try {
    const r = await fetch("/api/profile");
    const data = await r.json();
    if (!data.ok) return;
    const nameEl = $("sp-name");
    if (data.has_profile) {
      nameEl.hidden = false;
      nameEl.textContent = data.name || "unnamed";
      $("sp-editor").hidden = false;
      spOriginal = JSON.stringify(data.profile, null, 2);
      // Don't clobber unsaved edits on a passive refresh.
      if (!$("sp-json").value || $("sp-json").value === spOriginal) {
        $("sp-json").value = spOriginal;
      }
      $("sp-hint").textContent = "View and edit your current saved profile, or restore an older version.";
    } else {
      nameEl.hidden = true;
      $("sp-editor").hidden = true;
      $("sp-hint").textContent = "No profile saved yet. Generate a resume (or paste a profile) to create one.";
    }
    renderVersions(data.versions || []);
  } catch (e) { /* leave panel as-is */ }
}

function renderVersions(versions) {
  $("sp-version-count").textContent = String(versions.length);
  const wrap = $("sp-versions");
  if (!versions.length) {
    wrap.innerHTML = `<div class="sp-versions-empty">No saved versions yet.</div>`;
    return;
  }
  wrap.innerHTML = versions.map((v, i) => `
    <div class="sp-version-item">
      <div>
        <div class="sp-vi-meta">${escapeHtml(v.name || "unnamed")}${i === 0 ? " · current" : ""}</div>
        <div class="sp-vi-sub">${escapeHtml(v.saved_at)}${v.source ? " · " + escapeHtml(v.source) : ""}</div>
      </div>
      <div class="sp-vi-controls">
        <button class="link-btn sp-view" data-id="${escapeHtml(v.id)}" type="button">View</button>
        <button class="link-btn sp-restore" data-id="${escapeHtml(v.id)}" type="button">Restore</button>
        <button class="link-btn danger sp-del" data-id="${escapeHtml(v.id)}" type="button">Delete</button>
      </div>
    </div>`).join("");
  wrap.querySelectorAll(".sp-view").forEach((b) => b.addEventListener("click", () => viewVersion(b.dataset.id)));
  wrap.querySelectorAll(".sp-restore").forEach((b) => b.addEventListener("click", () => restoreVersion(b.dataset.id)));
  wrap.querySelectorAll(".sp-del").forEach((b) => b.addEventListener("click", () => deleteVersion(b.dataset.id)));
}

function spStatus(msg) {
  const el = $("sp-status");
  el.textContent = msg;
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 3000);
}

async function saveProfileEdits() {
  showError("");
  let parsed;
  try {
    parsed = JSON.parse($("sp-json").value);
  } catch (e) {
    showError("Profile is not valid JSON: " + e.message);
    return;
  }
  if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
    showError("Profile must be a JSON object.");
    return;
  }
  const btn = $("sp-save");
  setBusy2(btn, true, "Save changes");
  try {
    const r = await fetch("/api/profile/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: parsed }),
    });
    const data = await r.json();
    if (!data.ok) { showError(data.error || "Save failed."); return; }
    spStatus("Saved");
    loadSavedProfile();
    if (typeof loadStatus === "function") loadStatus();
  } catch (e) { showError("Network error: " + e.message); }
  finally { setBusy2(btn, false, "Save changes"); }
}

function setBusy2(btn, busy, label) {
  btn.disabled = busy;
  const l = btn.querySelector(".btn-label");
  if (l) l.textContent = busy ? "Working..." : label;
  const sp = btn.querySelector(".spinner");
  if (sp) sp.hidden = !busy;
}

let spViewingId = null;
async function viewVersion(id) {
  showError("");
  try {
    const r = await fetch("/api/profile/version", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    const data = await r.json();
    if (!data.ok) { showError(data.error || "Could not load version."); return; }
    spViewingId = id;
    $("sp-vv-title").textContent = "Version " + id;
    $("sp-vv-json").textContent = JSON.stringify(data.profile, null, 2);
    $("sp-version-view").hidden = false;
    $("sp-version-view").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { showError("Network error: " + e.message); }
}

async function restoreVersion(id) {
  if (!confirm("Restore this version as your current profile? Your current profile is already snapshotted in history.")) return;
  showError("");
  try {
    const r = await fetch("/api/profile/restore", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    const data = await r.json();
    if (!data.ok) { showError(data.error || "Restore failed."); return; }
    $("sp-json").value = JSON.stringify(data.profile, null, 2);
    spOriginal = $("sp-json").value;
    $("sp-version-view").hidden = true;
    spStatus("Restored");
    loadSavedProfile();
    if (typeof loadStatus === "function") loadStatus();
  } catch (e) { showError("Network error: " + e.message); }
}

async function deleteVersion(id) {
  if (!confirm("Delete this saved version permanently?")) return;
  try {
    const r = await fetch("/api/profile/version/delete", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    const data = await r.json();
    renderVersions(data.versions || []);
    if (spViewingId === id) $("sp-version-view").hidden = true;
  } catch (e) { showError("Network error: " + e.message); }
}

function init() {
  loadStatus();
  $("profile-toggle").addEventListener("click", toggleProfile);
  $("clear-profile").addEventListener("click", clearProfile);
  $("resume-file").addEventListener("change", onFile);
  $("load-sample-profile").addEventListener("click", () => {
    $("profile").value = JSON.stringify(SAMPLE_PROFILE, null, 2);
    if ($("profile-wrap").hidden) toggleProfile();
  });
  $("load-sample-jd").addEventListener("click", () => { $("jd").value = SAMPLE_JD; });
  document.querySelectorAll("[data-target]").forEach((b) => {
    if (b.id && b.id.startsWith("paste-")) {
      b.addEventListener("click", () => pasteFromClipboard(b.dataset.target));
    }
  });
  $("generate").addEventListener("click", () => generate());
  $("regenerate").addEventListener("click", regenerateWithGaps);
  $("toggle-tex").addEventListener("click", () => {
    const wrap = $("tex-editor-wrap");
    wrap.hidden = !wrap.hidden;
    $("toggle-tex").textContent = wrap.hidden ? "Edit LaTeX" : "Hide LaTeX";
  });
  $("recompile-tex").addEventListener("click", recompileTex);

  // saved profile / history
  $("sp-refresh").addEventListener("click", loadSavedProfile);
  $("sp-save").addEventListener("click", saveProfileEdits);
  $("sp-format").addEventListener("click", () => {
    try { $("sp-json").value = JSON.stringify(JSON.parse($("sp-json").value), null, 2); showError(""); }
    catch (e) { showError("Can't reformat — invalid JSON: " + e.message); }
  });
  $("sp-revert").addEventListener("click", () => { $("sp-json").value = spOriginal; spStatus("Reverted"); });
  $("sp-vv-close").addEventListener("click", () => { $("sp-version-view").hidden = true; });
  $("sp-vv-restore").addEventListener("click", () => { if (spViewingId) restoreVersion(spViewingId); });
  loadSavedProfile();
}

document.addEventListener("DOMContentLoaded", init);
