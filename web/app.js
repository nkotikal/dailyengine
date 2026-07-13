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
  const instructions = ($("instructions").value || "").trim();
  if (instructions) payload.instructions = instructions;
  if ($("fresh-pass").checked) payload.fresh_pass = true;
  const boldSpec = ($("bold-spec").value || "").trim();
  if ($("bold-toggle").checked || boldSpec) payload.bold = true;
  if (boldSpec) payload.bold_spec = boldSpec;

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

    renderDiff(data.diff || "", data.changed, data.profile_source);

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

function renderDiff(diff, changed, profileSource) {
  const btn = $("toggle-diff");
  const wrap = $("diff-wrap");
  const view = $("diff-view");
  const badge = $("diff-badge");
  if (!diff) {
    btn.hidden = true;
    wrap.hidden = true;
    view.innerHTML = "";
    // Only nudge on an iteration that produced no change (a common "it stopped
    // making changes" case) - not on a first build.
    if (changed === false && profileSource === "optimized") {
      badge.hidden = true;
      showError("No changes this run — the current draft already satisfies the request. "
        + "Put a new instruction in \"Additional context / instructions\" (e.g. what to "
        + "emphasize, shorten, or reorder) to change it.");
    }
    return;
  }
  let adds = 0, dels = 0;
  const html = diff.split("\n").map((line) => {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
      return `<span class="diff-hunk">${escapeHtml(line)}</span>`;
    }
    if (line.startsWith("+")) { adds++; return `<span class="diff-add">${escapeHtml(line)}</span>`; }
    if (line.startsWith("-")) { dels++; return `<span class="diff-del">${escapeHtml(line)}</span>`; }
    return `<span class="diff-ctx">${escapeHtml(line)}</span>`;
  }).join("\n");
  view.innerHTML = html;
  badge.hidden = false;
  badge.innerHTML = `<span class="diff-badge-add">+${adds}</span> <span class="diff-badge-del">-${dels}</span>`;
  btn.hidden = false;
  wrap.hidden = false;  // auto-open so changes are immediately visible
  $("toggle-diff").firstChild.textContent = "Hide changes ";
}

// ---- ATS-ify: strip any resume to the ATS-friendly one-page layout ----
let pendingAtsPdf = null;

function clearAtsFile() {
  pendingAtsPdf = null;
  const chip = $("ats-file-chip");
  chip.hidden = true; chip.innerHTML = "";
  $("ats-file").value = "";
}

async function onAtsFile(e) {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  $("ats-error").hidden = true;
  const name = f.name.toLowerCase();
  const chip = $("ats-file-chip");
  try {
    if (name.endsWith(".pdf")) {
      pendingAtsPdf = await fileToBase64(f);
      chip.hidden = false;
      chip.innerHTML = `${escapeHtml(f.name)} <span class="chip-x" title="Remove">&times;</span>`;
    } else {
      $("ats-input").value = await fileToText(f);
      pendingAtsPdf = null;
      chip.hidden = false;
      chip.innerHTML = `${escapeHtml(f.name)} (loaded below) <span class="chip-x" title="Remove">&times;</span>`;
    }
    chip.querySelector(".chip-x").addEventListener("click", clearAtsFile);
  } catch (err) {
    $("ats-error").textContent = "Could not read that file.";
    $("ats-error").hidden = false;
  }
}

async function runAtsify() {
  const err = $("ats-error");
  err.hidden = true;
  const text = $("ats-input").value.trim();
  if (!text && !pendingAtsPdf) {
    err.textContent = "Upload a résumé (PDF/text/LaTeX) or paste LaTeX/text first.";
    err.hidden = false;
    return;
  }
  const btn = $("ats-run");
  setBusy2(btn, true, "Strip to ATS-friendly one page");
  try {
    const payload = { model: $("model").value || null };
    if (text) payload.source_text = text;
    if (pendingAtsPdf) payload.resume_pdf_base64 = pendingAtsPdf;
    const r = await fetch("/api/atsify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!data.ok) { err.textContent = data.error || "ATS conversion failed."; err.hidden = false; return; }
    updatePdfPreview(data.pdf_base64, data.tex);
    $("tex-editor").value = data.tex;
    $("tex-editor-wrap").hidden = true;
    $("toggle-tex").textContent = "Edit LaTeX";
    renderDiff("", null);
    $("summary-box").hidden = true;
    const meta = $("result-meta");
    meta.hidden = false;
    const who = data.profile_name ? ` (${data.profile_name})` : "";
    meta.textContent = `${data.pages} page · ATS-stripped${who}`;
    $("result-empty").hidden = true;
    $("result-live").hidden = false;
    if (data.warnings && data.warnings.length) { err.textContent = data.warnings.join(" "); err.hidden = false; }
    clearAtsFile();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    err.textContent = "Network error: " + e.message;
    err.hidden = false;
  } finally {
    setBusy2(btn, false, "Strip to ATS-friendly one page");
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

// -- user switcher (per-user compartmentalization) ------------------------

async function loadUsers() {
  try {
    const r = await fetch("/api/users");
    const data = await r.json();
    if (!data.ok) return;
    const sel = $("user-select");
    if (!sel) return;
    sel.innerHTML = "";
    (data.users || []).forEach((u) => {
      const o = document.createElement("option");
      o.value = u.id;
      o.textContent = u.name || u.id;
      if (u.id === data.active) o.selected = true;
      sel.appendChild(o);
    });
    const del = $("user-delete");
    if (del) del.disabled = (data.users || []).length <= 1;
  } catch (e) { /* non-fatal */ }
}

async function switchUser(id) {
  try {
    const r = await fetch("/api/users/switch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await r.json();
    if (!data.ok) { alert(data.error || "Could not switch user."); return; }
    // Reload so every tab repopulates from the newly active user's data.
    location.reload();
  } catch (e) { alert("Network error: " + e.message); }
}

async function addUser() {
  const name = (prompt("Name for the new user?") || "").trim();
  if (!name) return;
  try {
    const r = await fetch("/api/users/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await r.json();
    if (!data.ok) { alert(data.error || "Could not create user."); return; }
    location.reload();  // new user is now active and starts empty/isolated
  } catch (e) { alert("Network error: " + e.message); }
}

async function renameUser() {
  const sel = $("user-select");
  if (!sel || !sel.value) return;
  const cur = sel.options[sel.selectedIndex].textContent;
  const name = (prompt("Rename user:", cur) || "").trim();
  if (!name || name === cur) return;
  try {
    await fetch("/api/users/rename", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: sel.value, name }),
    });
    loadUsers();
  } catch (e) { alert("Network error: " + e.message); }
}

async function deleteUser() {
  const sel = $("user-select");
  if (!sel || !sel.value) return;
  const cur = sel.options[sel.selectedIndex].textContent;
  if (!confirm(`Delete user "${cur}" and ALL of their data permanently? This cannot be undone.`)) return;
  try {
    const r = await fetch("/api/users/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: sel.value }),
    });
    const data = await r.json();
    if (!data.ok) { alert(data.error || "Could not delete user."); return; }
    location.reload();
  } catch (e) { alert("Network error: " + e.message); }
}

// -- dashboard localization (Korean mode) ----------------------------------
// Static-shell translation: maps exact English UI strings to Korean and swaps
// leaf text/placeholders in-place (reversible). Dynamic lists stay in the source
// language; the emailed report is translated server-side.
const I18N_KO = {
  // tabs + sub-tabs
  "Resume": "이력서", "Daily Digest": "데일리 다이제스트", "Memory": "메모리",
  "Digest": "다이제스트", "Plan": "계획", "Sources": "소스", "Learning": "학습", "Settings": "설정",
  // panel titles
  "About you": "내 정보", "Delivery": "발송 설정", "Schedule → Calendar": "일정 → 캘린더",
  "Weekly tasks": "주간 작업", "Trackers": "트래커", "Language practice": "언어 연습",
  "Reminders & deadlines": "리마인더 및 마감일", "Headlines & interests": "헤드라인 및 관심사",
  "Clear & reset": "초기화 및 리셋", "Updates": "업데이트", "Latest reflection": "최근 회고",
  "Preview": "미리보기", "Context": "컨텍스트", "Job description": "채용 공고",
  "Coverage gaps": "부족한 부분", "Saved profile": "저장된 프로필", "Version history": "버전 기록",
  "Profile — base context": "프로필 — 기본 컨텍스트", "Teach it about you": "나에 대해 알려주기",
  "Talk to your memory": "메모리와 대화", "What it remembers": "기억하는 내용",
  // labels
  "About you / context": "내 정보 / 컨텍스트", "Goals this week": "이번 주 목표",
  "Long-term goals (with target dates)": "장기 목표 (목표 날짜 포함)",
  "Recurring / standing tasks": "반복 / 상시 작업", "Send to": "받는 사람",
  "Interests (comma-separated)": "관심사 (쉼표로 구분)", "Sources": "소스",
  "Model (primary)": "모델 (기본)", "OpenAI fallback model": "OpenAI 대체 모델",
  "Send time (local)": "발송 시간 (현지)", "Focus capacity (h/day)": "집중 시간 (시간/일)",
  "Morning auto-send": "아침 자동 발송", "Offline mode": "오프라인 모드",
  "Include in digest:": "다이제스트에 포함:", "Language": "언어", "Type": "유형", "Name": "이름",
  "Korean level / placement": "한국어 레벨 / 배치", "English vocab level": "영어 어휘 레벨",
  // buttons
  "Save details": "세부정보 저장", "Add": "추가", "Preview digest": "다이제스트 미리보기",
  "Send now": "지금 보내기", "Resend with updates": "업데이트 후 재전송", "Parse & save": "분석 및 저장",
  "Push to Google Calendar": "구글 캘린더에 추가", "Clear completed": "완료 항목 삭제",
  "Clear all": "모두 삭제", "+ Add task": "+ 작업 추가", "Test": "테스트", "Add tracker": "트래커 추가",
  "Preview today's lesson": "오늘의 수업 미리보기", "Set placement": "레벨 설정",
  "Add reminder": "리마인더 추가", "Add source": "소스 추가",
  "Save interests & sources": "관심사 및 소스 저장", "Process email replies now": "이메일 답장 처리",
  "Reset ALL content": "모든 콘텐츠 초기화", "Generate resume": "이력서 생성",
  "Save profile": "프로필 저장", "Apply": "적용", "Add as one memory": "하나의 메모리로 추가",
  "Consolidate memory now": "메모리 통합", "Add to memory": "메모리에 추가", "Refresh": "새로고침",
  // clear/reset grid
  "Daily tasks": "일일 작업", "Weekly goals": "주간 목표", "Long-term goals": "장기 목표",
  "Schedule": "일정", "Reminders": "리마인더", "Korean progress": "한국어 진행상황",
  // header controls
  "+ New": "+ 새 사용자", "Rename": "이름 변경", "Delete": "삭제",
};

function _translateNode(node, dict) {
  if (node.children.length === 0) {
    const cur = node.textContent;
    const key = cur.trim();
    if (dict) {
      if (dict[key] !== undefined) {
        if (!node.hasAttribute("data-en")) node.setAttribute("data-en", cur);
        node.textContent = cur.replace(key, dict[key]);
      }
    } else if (node.hasAttribute("data-en")) {
      node.textContent = node.getAttribute("data-en");
      node.removeAttribute("data-en");
    }
  }
  if ("placeholder" in node && node.placeholder) {
    const key = node.placeholder.trim();
    if (dict && dict[key] !== undefined) {
      if (!node.hasAttribute("data-en-ph")) node.setAttribute("data-en-ph", node.placeholder);
      node.placeholder = dict[key];
    } else if (!dict && node.hasAttribute("data-en-ph")) {
      node.placeholder = node.getAttribute("data-en-ph");
      node.removeAttribute("data-en-ph");
    }
  }
}

function applyUILang(lang) {
  const ko = lang === "ko";
  document.documentElement.setAttribute("lang", ko ? "ko" : "en");
  const dict = ko ? I18N_KO : null;
  const shell = document.querySelector("main.shell");
  if (shell) shell.querySelectorAll("*").forEach((n) => _translateNode(n, dict));
  const sel = document.getElementById("lang-select");
  if (sel) sel.value = ko ? "ko" : "en";
}
window.applyUILang = applyUILang;

function initLangSwitcher() {
  const sel = $("lang-select");
  if (!sel) return;
  let saved = "en";
  try { saved = localStorage.getItem("rf-lang") || "en"; } catch (e) {}
  applyUILang(saved);
  sel.addEventListener("change", () => {
    const l = sel.value === "ko" ? "ko" : "en";
    try { localStorage.setItem("rf-lang", l); } catch (e) {}
    applyUILang(l);
    fetch("/api/digest/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ui_lang: l }),
    }).catch(() => {});
  });
}

// -- color theme switcher --------------------------------------------------

function initThemeSwitcher() {
  const sel = $("theme-select");
  if (!sel) return;
  let saved = "aurora";
  try { saved = localStorage.getItem("rf-theme") || "aurora"; } catch (e) {}
  sel.value = saved;
  if (saved && saved !== "aurora") {
    document.documentElement.setAttribute("data-theme", saved);
  }
  sel.addEventListener("change", () => {
    const t = sel.value;
    if (t && t !== "aurora") {
      document.documentElement.setAttribute("data-theme", t);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try { localStorage.setItem("rf-theme", t); } catch (e) {}
    // Persist per-user so each profile keeps its own theme.
    fetch("/api/digest/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: t }),
    }).catch(() => {});
  });
}

// -- backdrop pattern switcher --------------------------------------------

function initPatternSwitcher() {
  const sel = $("pattern-select");
  if (!sel) return;
  let saved = "moroccan";
  try { saved = localStorage.getItem("rf-pattern") || "moroccan"; } catch (e) {}
  sel.value = saved;
  document.documentElement.setAttribute("data-pattern", saved);
  sel.addEventListener("change", () => {
    const p = sel.value || "moroccan";
    document.documentElement.setAttribute("data-pattern", p);
    try { localStorage.setItem("rf-pattern", p); } catch (e) {}
    fetch("/api/digest/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pattern: p }),
    }).catch(() => {});
  });
}

function initUserSwitcher() {
  const sel = $("user-select");
  if (!sel) return;
  loadUsers();
  sel.addEventListener("change", () => switchUser(sel.value));
  if ($("user-add")) $("user-add").addEventListener("click", addUser);
  if ($("user-rename")) $("user-rename").addEventListener("click", renameUser);
  if ($("user-delete")) $("user-delete").addEventListener("click", deleteUser);
}

function init() {
  loadStatus();
  initThemeSwitcher();
  initPatternSwitcher();
  initLangSwitcher();
  initUserSwitcher();
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
  $("ats-run").addEventListener("click", runAtsify);
  $("ats-file").addEventListener("change", onAtsFile);
  $("toggle-diff").addEventListener("click", () => {
    const wrap = $("diff-wrap");
    wrap.hidden = !wrap.hidden;
    $("toggle-diff").firstChild.textContent = wrap.hidden ? "View changes " : "Hide changes ";
  });

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
