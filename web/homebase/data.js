// Home Base data layer: talks to the server, then turns the weekly task forest
// into the derived numbers the 3D scene and the HUD both read.
//
// Tasks themselves live in weekly_tasks.json (shared with the digest); anything
// Home Base adds on top - icons, descriptions, notes, chat - comes back as `meta`.

const PRIORITY_WEIGHT = { critical: 6, high: 3, medium: 2, low: 1 };

export const store = {
  tasks: [],
  summary: {},
  meta: {},
  prefs: { scene_theme: "space", filter: "week", quality: "high" },
  weeklyGoals: "",
  offline: false,
  llmReady: false,
  index: new Map(),   // id -> { node, parent, chain, depth, due }
  stats: new Map(),   // id -> { total, done, pct, priority, dueDays, overdue, match }
};

// --- transport --------------------------------------------------------------

export async function req(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* server sent a non-JSON error */ }
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

/** Fold a server response into the store. Any task endpoint returns {tasks, summary}. */
export function absorb(data, filter) {
  if (Array.isArray(data.tasks)) store.tasks = data.tasks;
  if (data.summary) store.summary = data.summary;
  if (data.meta) store.meta = data.meta;
  if (data.prefs) store.prefs = { ...store.prefs, ...data.prefs };
  if (typeof data.weekly_goals === "string") store.weeklyGoals = data.weekly_goals;
  if (typeof data.offline === "boolean") store.offline = data.offline;
  if (typeof data.llm_ready === "boolean") store.llmReady = data.llm_ready;
  reindex(filter);
  return store;
}

export async function loadState(filter) {
  return absorb(await req("/api/homebase/state"), filter);
}

// --- dates ------------------------------------------------------------------

export function todayISO(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function parseISO(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}

/** Whole days from today to `iso`; negative means overdue, null when undated. */
export function dueDays(iso, today = todayISO()) {
  const a = parseISO(iso);
  const b = parseISO(today);
  if (!a || !b) return null;
  return Math.round((a - b) / 86400000);
}

/** Days left in the current Mon-Sun week, counting today as 0. */
function daysLeftInWeek(today = todayISO()) {
  const d = parseISO(today);
  if (!d) return 6;
  const dow = (d.getDay() + 6) % 7; // Monday = 0
  return 6 - dow;
}

export function weekdayOf(iso) {
  const d = parseISO(iso);
  return d ? d.getDay() : -1; // 0 = Sunday
}

export function fmtEst(minutes) {
  const m = Math.max(0, parseInt(minutes, 10) || 0);
  if (!m) return "";
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (!h) return `${rest}m`;
  return rest ? `${h}h ${rest}m` : `${h}h`;
}

export function fmtDue(iso, today = todayISO()) {
  if (!iso) return "";
  const d = dueDays(iso, today);
  if (d === null) return iso;
  if (d === 0) return "today";
  if (d === 1) return "tomorrow";
  if (d === -1) return "1 day late";
  if (d < 0) return `${-d} days late`;
  if (d < 7) return `in ${d} days`;
  return iso;
}

// --- filters ----------------------------------------------------------------

export const FILTERS = ["week", "today", "overdue", "nodue", "all"];

export const FILTER_LABEL = {
  week: "due this week",
  today: "due today",
  overdue: "overdue",
  nodue: "with no due date",
  all: "across everything",
};

/** Does one node fall inside the active filter? `filter` is {kind, day}. */
export function matches(id, filter, today = todayISO()) {
  const entry = store.index.get(id);
  if (!entry) return false;
  const due = entry.due;
  const kind = filter && filter.kind ? filter.kind : "week";
  if (kind === "all") return true;
  if (kind === "nodue") return !due;
  if (!due) return false;
  const delta = dueDays(due, today);
  if (delta === null) return false;
  if (kind === "week") return delta <= daysLeftInWeek(today);
  if (kind === "today") return delta === 0;
  if (kind === "overdue") return delta < 0;
  if (kind === "day") return weekdayOf(due) === filter.day;
  return true;
}

// --- tree -------------------------------------------------------------------

export function kids(node) {
  return (node && node.subtasks) || [];
}

export function isLeaf(node) {
  return kids(node).length === 0;
}

export function walk(nodes, fn) {
  (nodes || []).forEach((n) => { fn(n); walk(kids(n), fn); });
}

export function chainOf(id) {
  const entry = store.index.get(id);
  return entry ? entry.chain : [];
}

export function nodeById(id) {
  const entry = store.index.get(id);
  return entry ? entry.node : null;
}

export function entryOf(id) {
  return store.index.get(id) || null;
}

export function metaOf(id) {
  return store.meta[id] || {};
}

/**
 * Rebuild the id index and the per-node rollups the scene draws from.
 *
 * Counting mirrors the server's `_count_leaves`: a node with children is a
 * grouping, so only childless nodes count as real tasks. Due dates cascade -
 * a subtask with no date inherits its nearest dated ancestor.
 */
export function reindex(filter) {
  const today = todayISO();
  store.index = new Map();
  store.stats = new Map();

  (function build(nodes, parent, chain, inheritedDue, depth) {
    (nodes || []).forEach((n) => {
      if (!n || !n.id) return;
      const due = (n.due || "").trim() || inheritedDue;
      const mine = chain.concat([n]);
      store.index.set(n.id, { node: n, parent, chain: mine, depth, due });
      build(kids(n), n, mine, due, depth + 1);
    });
  })(store.tasks, null, [], "", 0);

  (function roll(nodes) {
    const agg = { total: 0, done: 0, matched: 0, matchedDone: 0 };
    (nodes || []).forEach((n) => {
      if (!n || !n.id) return;
      const entry = store.index.get(n.id);
      const children = kids(n);
      const mine = children.length
        ? roll(children)
        : (() => {
          const hit = matches(n.id, filter, today);
          return {
            total: 1,
            done: n.done ? 1 : 0,
            matched: hit ? 1 : 0,
            matchedDone: hit && n.done ? 1 : 0,
          };
        })();

      let priority = n.priority || "medium";
      let soonest = entry.due ? dueDays(entry.due, today) : null;
      children.forEach((c) => {
        const cs = store.stats.get(c.id);
        if (!cs) return;
        if ((PRIORITY_WEIGHT[cs.priority] || 2) > (PRIORITY_WEIGHT[priority] || 2)) {
          priority = cs.priority;
        }
        if (cs.dueDays !== null && (soonest === null || cs.dueDays < soonest)) {
          soonest = cs.dueDays;
        }
      });

      store.stats.set(n.id, {
        total: mine.total,
        done: mine.done,
        pct: mine.total ? mine.done / mine.total : 0,
        matched: mine.matched,
        matchedDone: mine.matchedDone,
        match: mine.matched > 0,
        priority,
        dueDays: soonest,
        overdue: soonest !== null && soonest < 0 && mine.done < mine.total,
        leaf: children.length === 0,
        depth: entry.depth,
      });

      agg.total += mine.total;
      agg.done += mine.done;
      agg.matched += mine.matched;
      agg.matchedDone += mine.matchedDone;
    });
    return agg;
  })(store.tasks);

  return store;
}

/** completed / total for the active filter, counting leaves only. */
export function progress(filter) {
  let done = 0;
  let total = 0;
  walk(store.tasks, (n) => {
    if (!isLeaf(n)) return;
    const st = store.stats.get(n.id);
    if (!st || !st.matched) return;
    total += 1;
    if (n.done) done += 1;
  });
  return { done, total, pct: total ? done / total : 0 };
}

export function statsOf(id) {
  return store.stats.get(id) || {
    total: 0, done: 0, pct: 0, matched: 0, match: true,
    priority: "medium", dueDays: null, overdue: false, leaf: true, depth: 0,
  };
}
