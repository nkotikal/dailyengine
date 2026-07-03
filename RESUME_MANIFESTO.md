# The Resume Manifesto

A reference standard for generating resumes that pass every gate: automated ATS
parsers, time-pressured non-technical recruiters, and deep technical hiring
managers. This document is injected into the LLM optimizer's instructions and
should be honored on every generation.

Synthesized from: Google's XYZ formula (Laszlo Bock, *Work Rules!*), big-tech
hardware/deep-tech recruiting guidance (Workday ATS; domain-depth emphasis;
measurable outcomes), and consistent 2026 guidance from ATS
vendors and recruiters (Jobscan, recruiter 6-second-scan studies, "I reviewed
400 resumes" practitioner reports).

---

## 1. Know your four readers

A resume is read, in sequence, by four personas. It must satisfy all four.

1. **The ATS parser (machine).** Extracts text into structured fields and scores
   keyword overlap with the job description. It does not "see" design; it reads a
   single top-to-bottom, left-to-right text stream. If it cannot parse a field,
   that content effectively does not exist.
2. **The recruiter, 6-second scan (non-technical).** Pattern-matches, not reads.
   Checks five zones in order: (1) name + target title, (2) most-recent role's
   title/employer/dates, (3) skills, (4) the first bullet of the most-recent
   role, (5) a fast top-to-bottom sweep. Most never read past the second bullet.
3. **The recruiter, detailed pass.** Confirms minimum requirements: years of
   experience, degree, relevant titles, must-have skills.
4. **The technical hiring manager (deep).** The most thorough reader. Looks for
   evidence your past work resembles the role, measurable impact at appropriate
   scope, ownership/growth signals, and genuine domain depth.

## 2. The three questions every reviewer answers in ~25 seconds

Every bullet, skill, and ordering decision should help answer these:

1. **Have you done this?** (relevant titles, companies, technologies, domain)
2. **Did it matter?** (quantified impact; outcomes, not responsibilities)
3. **Are you the right level?** (scope and autonomy language signal seniority
   faster and more reliably than years listed)

If a line does not advance one of these answers, cut it or rewrite it.

## 3. The bullet formula: Google XYZ

Write every experience and project bullet as:

> **Accomplished [X] as measured by [Y], by doing [Z].**

- **X — outcome:** what improved/shipped/changed. Start with a strong action verb.
- **Y — metric:** a number that proves it (%, ms, GB/s, $, users, req/day, ×,
  uptime, p95 latency, coverage, deployment frequency, incident reduction).
- **Z — method:** the technical approach, tools, or systems used.

Order is flexible (lead with the metric if it is impressive), but all three
elements must be present. Examples:

- "Cut p95 latency 38% (Y) by sharding a FastAPI service and adding Redis caching
  (Z), sustaining 12M requests/day (X)."
- "Reduced deploy time from 45 min to 6 min (Y) by migrating a monolith to
  Kubernetes with Terraform-managed infra (Z)."

Rules for bullets:

- Lead with strong action verbs (Architected, Led, Built, Shipped, Optimized,
  Reduced, Scaled, Automated, Designed, Owned). Never start with "Responsible
  for" / "Worked on" / "Helped with."
- One to two lines each. Dense, single-fact bullets beat long compound ones.
- The **first bullet of the most-recent role is the single most-read sentence on
  the resume after the name** - it must contain a number and a marquee outcome.
- Prefer concrete, defensible, specific results over adjectives ("robust",
  "cutting-edge", "passionate" are noise).

## 4. Metrics and honesty

- Quantify wherever truthful. If a hard number is genuinely unavailable, use
  credible proxies: team size, user/customer scale, request volume, data size,
  adoption rate, incident/defect reduction, time saved (days -> hours).
- **Never fabricate numbers, employers, titles, dates, degrees, or
  certifications.** Invented metrics are worse than none - they fail technical
  interviews and can get a candidate rejected or fired.
- You MAY rephrase boldly, surface skills genuinely implied by described work,
  reorder, and shift emphasis. Keep every factual anchor intact.

## 5. ATS mechanics (hard constraints)

- **Single column. No tables, columns, text boxes, graphics, icons, or skill
  bars.** Parsers read in one stream; multi-column and tables scramble content.
- **Standard section headings only:** "Experience" / "Work Experience",
  "Education", "Projects", "Technical Skills"/"Skills". Creative headings get
  miscategorized or skipped.
- **All content in the document body.** Never put contact info or anything
  important in a page header/footer - many parsers ignore those zones.
- **Contact line:** full name, then phone, email, and plain-text profile URLs
  (e.g., `linkedin.com/in/name`, `github.com/name`). Spell URLs as text; some ATS
  strip hyperlinks. Use a universal phone format.
- **Fonts 10-12pt body, standard families.** Standard round/dash bullets only.
- **Keyword strategy:** mirror the job description's exact phrasing where it
  truthfully applies. Include both the spelled-out term and its acronym on first
  use where it aids matching (e.g., "CI/CD (continuous integration / continuous
  delivery)", "Kubernetes (K8s)"). Put the most important matching terms where
  both humans and parsers look first: the skills section and the top bullets.
- **Consistent date formatting** throughout (e.g., `Mon YYYY -- Mon YYYY`).

## 6. Ordering and prioritization (front-load relevance)

- Reorder skill categories so the most job-relevant category appears first; order
  skills within each category most-relevant first.
- Within each role/project, put the most JD-relevant, highest-impact bullet
  first.
- Keep the most-recent role and the strongest evidence in the **top third** of
  the page.
- When trimming for one page, drop the least JD-relevant bullets entirely rather
  than shrinking everything into filler. Keep ~4-5 bullets on the most recent
  role, ~2-3 on older roles, ~2 per project.

## 7. Level / scope signaling

Seniority is communicated by scope language, not years:

- **Senior signals:** autonomous technical decisions, cross-functional
  influence, system-wide/architectural ownership, mentoring, setting standards,
  driving initiatives to completion.
- **Junior/mid signals:** executing tickets, shipping assigned features,
  supporting others' work.

Match the language to the level the job description targets, truthfully.

## 8. Technical-depth signals (especially deep-tech / hardware & systems roles)

- **Depth over breadth.** Specialists beat generalists. Surface concrete domain
  depth (e.g., for systems/GPU roles: CUDA, kernels, memory hierarchy,
  parallelism, profiling, TensorRT/PyTorch internals, distributed training).
- **Lead with the exact stack the role keyword-scans for** in both skills and top
  bullets; do not bury it.
- Use precise, defensible terminology and real performance units (ms, GB/s, fps,
  TOPS/W, throughput ×, occupancy). Vague "machine learning" buzzwords read as
  shallow to expert reviewers.
- Link credibility where available and provided in the profile: GitHub,
  papers/preprints, patents, notable open-source contributions.

## 9. Tailoring to the specific job description

- Identify the core problem the role is hiring to solve and mirror that language.
  ("Scale to 10x users" -> emphasize performance/system-design evidence;
  "own the data pipeline" -> emphasize reliability/ownership evidence.)
- Pull must-have skills and keywords from the JD and ensure the truthful ones are
  visibly present in the skills section and top bullets.
- Re-rank all content by relevance to this specific JD on every generation.

## 10. One page

- Default to a single page. Be ruthless: cut the least relevant content first,
  then tighten phrasing. Readability and ATS-safety floors (>= 10pt font,
  standard layout) are never sacrificed to fit.

## 11. Working within this template (constraints)

This pipeline renders the Jake Gutierrez single-column template, which is already
ATS-safe (single column, standard headings, body-text contact line, selectable
text via `\pdfgentounicode=1`). The optimizer controls **content only** and must
return the same JSON schema: `contact`, `education`, `skills`, `experience`
(with `bullets`), `projects` (with `tech`, `bullets`). It must not invent new
sections (the template has no summary/objective block) and must keep the contact
block factual and unchanged.

---

### Quick checklist (apply every generation)

- [ ] Each bullet uses XYZ; starts with an action verb; contains a number or
      credible proxy; is 1-2 lines.
- [ ] First bullet of the most-recent role has a marquee, quantified outcome.
- [ ] Skills and top bullets carry the JD's exact must-have keywords (truthfully),
      acronyms spelled out once where useful.
- [ ] Skill categories and bullets reordered most-relevant-first for this JD.
- [ ] Scope language matches the target level.
- [ ] No fabricated facts, numbers, titles, dates, or credentials.
- [ ] Fits one page; standard headings; contact in body; single column.
