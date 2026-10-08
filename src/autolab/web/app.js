// Autolab control room (D49). Vanilla ES module, no dependencies, no innerHTML with data:
// every node is built with h() and text goes through textContent, so ledger content can
// never inject markup. Live updates come from the server's SSE stream (/api/stream).

const TOKEN = document.querySelector('meta[name="autolab-token"]').content;
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ DOM helper
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// ------------------------------------------------------------------ formatting
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function ago(iso) {
  if (!iso) return "";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  const units = [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [u, n] of units) if (Math.abs(s) >= n) return rtf.format(Math.round(s / n), u);
  return "just now";
}
const absTime = (iso) => (iso ? new Date(iso).toLocaleString() : "");
function time(iso) { return h("time", { datetime: iso, title: absTime(iso), class: "when", text: ago(iso) }); }
const human = (s) => String(s ?? "").replaceAll("_", " ").toLowerCase();
// Lab vocabulary (states, tones, pipelines, stages, backends, ...) comes from /api/meta.
let META = { tones: {}, research_terminal: [], research_done: [], engineering_pipeline: [], pipeline_alias: {},
  project_kinds: [], stages: [], planes: [], backends: [], roles: [], presets: [], ui: {} };
const TONE_CLASS = { ok: "b-ok", bad: "b-bad", warn: "b-warn", info: "b-info", review: "b-violet" };
const toneOf = (v) => TONE_CLASS[META.tones[String(v ?? "")]] ?? "";
const isDone = (state) => META.research_done.includes(state);
const isTerminal = (state) => META.research_terminal.includes(state);
const pipelineStep = (state) => META.pipeline_alias[state] || state;
function badge(value, extra = "") {
  const v = String(value ?? "");
  return h("span", { class: `badge ${toneOf(v)} ${extra}`, text: human(v) });
}

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", "X-Autolab-Token": TOKEN },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ------------------------------------------------------------------ toasts
function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}`, role: kind === "bad" ? "alert" : "status", text: msg });
  $("toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 7000 : 3800);
}

// ------------------------------------------------------------------ theme
function applyTheme(t) {
  const theme = t || localStorage.getItem("autolab-theme") ||
    (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  document.documentElement.dataset.theme = theme;
  $("theme-btn").textContent = theme === "dark" ? "☀ Light theme" : "☾ Dark theme";
}
$("theme-btn")?.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("autolab-theme", next);
  applyTheme(next);
});

// ------------------------------------------------------------------ state + router
const store = { overview: null, projects: null, agents: null, approvals: null, activity: null };
let route = { name: "overview", id: null, tab: null };
let renderSeq = 0;

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const name = parts[0] || "overview";
  return { name, id: parts[1] || null, tab: parts[2] || null };
}
function go(path) { location.hash = path; }

async function loadMeta() {
  META = await api("/api/meta");
}
async function loadCore() {
  if (!META.version) await loadMeta();
  store.overview = await api("/api/overview");
  const o = store.overview;
  $("lab-name").textContent = o.lab;
  document.title = `${o.counts.approvals ? `(${o.counts.approvals}) ` : ""}Autolab · ${o.lab}`;
  $("nav-projects").textContent = o.counts.projects || "";
  $("nav-approvals").textContent = o.counts.approvals || "";
  const blocked = o.agents.filter((a) => a.status === "blocked" && a.stages.length).length;
  $("nav-agents").textContent = blocked ? `${blocked} blocked` : "";
  const l = o.ledger;
  $("ledger-dot").className = `dot ${l.ok ? "ok" : "bad"}`;
  $("ledger-text").textContent = l.ok ? `Ledger verified · ${l.events} events` : "Ledger verification FAILED";
  $("ledger-text").title = l.ok ? `head ${l.head}` : l.error;
}

async function render() {
  const seq = ++renderSeq;
  route = parseRoute();
  document.querySelectorAll("#nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.route === route.name) || a.removeAttribute("aria-current"));
  document.querySelector(`#nav a[data-route="${route.name}"]`)?.setAttribute("aria-current", "page");
  const view = $("view");
  if (!view.childElementCount) view.append(skeleton());
  try {
    await loadCore();
    const node = await (VIEWS[route.name] || VIEWS.overview)(route);
    if (seq !== renderSeq) return; // a newer render started
    const scroll = window.scrollY;
    view.replaceChildren(node);
    window.scrollTo(0, scroll);
  } catch (err) {
    if (seq !== renderSeq) return;
    view.replaceChildren(h("div", { class: "empty", text: `Could not load: ${err.message}` }));
  }
}
function skeleton() {
  return h("div", {}, h("div", { class: "skel" }), h("div", { class: "skel" }), h("div", { class: "skel" }));
}

// ------------------------------------------------------------------ shared pieces
function pageHead(title, sub, ...actions) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", { text: title }), sub ? h("p", { text: sub }) : null),
    actions.length ? h("div", { class: "actions" }, actions) : null);
}
function card(title, sub, ...body) {
  return h("section", { class: "card" },
    title ? h("div", { class: "card-head" }, h("h2", { text: title }), sub ? (sub instanceof Node ? sub : h("span", { class: "sub", text: sub })) : null) : null,
    body);
}
function kpi(label, value, cls = "") {
  return h("div", { class: `card kpi ${cls}` }, h("span", { class: "label", text: label }), h("span", { class: "value", text: value }));
}
function stepper(pipeline, current, done = false) {
  const idx = pipeline.indexOf(current);
  return h("div", { class: "stepper", role: "list", "aria-label": "Engineering pipeline" },
    pipeline.map((s, i) => h("div", {
      class: `step ${done || i < idx ? "done" : i === idx ? "current" : ""}`, role: "listitem",
      "aria-current": i === idx && !done ? "step" : null,
    }, h("div", { class: "bar" }), h("div", { text: human(s) }))));
}
function alertBox(a) {
  const icon = { error: "!", warn: "!", info: "i" }[a.level] || "i";
  return h("div", { class: `alert ${a.level}`, role: a.level === "error" ? "alert" : null },
    h("span", { class: "icon", text: icon }),
    h("div", {}, h("div", { class: "title", text: a.title }), a.detail ? h("div", { class: "detail", text: a.detail, title: a.detail }) : null),
    a.project ? h("a", { href: `#/projects/${a.project}`, text: "Open" }) : h("span"));
}
function logView(lines) {
  return h("pre", { class: "code log", "aria-label": "Queue log" }, lines.map((ln) => h("span", {
    class: /waiting/.test(ln) ? "l-wait" : /ERROR|HALTED|timed out/.test(ln) ? "l-err"
      : /COMPLETE|passed|approved/.test(ln) ? "l-ok" : /^(---|===|QUEUE)/.test(ln) ? "l-head" : "",
    text: ln + "\n",
  })));
}

// ------------------------------------------------------------------ views
const VIEWS = {};

VIEWS.overview = async () => {
  const o = store.overview;
  const c = o.counts;
  const out = h("div", {});
  out.append(pageHead("Overview", "The lab at a glance: gates, live work, agents and anything that needs you.",
    h("button", { class: "primary", onclick: newProjectDialog, text: "New project" })));
  if (o.alerts.length) out.append(h("div", { class: "alerts" }, o.alerts.map(alertBox)));
  out.append(h("div", { class: "grid kpis" },
    kpi("Active projects", c.active, c.active ? "attn" : ""), kpi("Awaiting your decision", c.approvals, c.approvals ? "attn" : ""),
    kpi("Agents working", c.agents_working), kpi("Delivered", c.deliveries), kpi("Halted", c.halted, c.halted ? "bad" : "")));
  const left = h("div", { class: "stack" });
  const right = h("div", { class: "stack" });

  // gate board
  const label = META.ui.milestone_label || "Milestone";
  const gates = h("div", { class: "gates" }, o.gates.length ? o.gates.map((g) => {
    const done = g.tasks.filter((t) => isDone(t.state)).length;
    const bar = h("span"); bar.style.width = `${Math.round((done / Math.max(1, g.tasks.length)) * 100)}%`;
    return h("div", { class: "gate-row" },
      h("div", { class: "gate-label" }, `${label} ${g.gate}`, h("span", { class: "muted", text: `${done}/${g.tasks.length} done` }),
        h("div", { class: "gate-progress", role: "progressbar", "aria-valuenow": done, "aria-valuemax": g.tasks.length }, bar)),
      h("div", { class: "gate-tasks" }, g.tasks.map((t) => h("button", {
        class: `gate-task ${isDone(t.state) ? "done" : isTerminal(t.state) ? "halt" : "live"}`,
        onclick: () => go(`/projects/${t.project}`), title: t.title,
      }, h("span", { class: "k", text: t.key }), h("span", { class: "s", text: isDone(t.state) ? human(t.state) : human(t.eng_state || t.state) })))));
  }) : h("div", { class: "empty", text: `No ${label.toLowerCase()} tasks yet.` }));
  if (META.ui.milestones_enabled || o.gates.length)
    left.append(card(`${label} progress`, `engineering tasks tagged with a ${label.toLowerCase()}`, gates));

  // active work
  for (const p of o.active) {
    const e = p.eng;
    left.append(card(`${p.key || p.id} · in progress`, h("a", { href: `#/projects/${p.id}`, text: "Details →" }),
      h("div", { class: "prose", text: p.title }),
      e ? [stepper(o.pipeline, pipelineStep(e.state)),
        h("div", { class: "metrics" },
          [["Review rounds", e.review_round], ["Patches", e.patch_attempts], ["Redesigns", e.redesigns], ["Test runs", e.test_runs]]
            .map(([l, v]) => h("div", { class: "metric" }, h("b", { text: v }), h("span", { text: l }))))] : badge(p.state)));
  }
  if (!o.active.length) left.append(card("Active work", null, h("div", { class: "empty", text: "Nothing in progress." })));

  // queue
  const q = o.queue;
  if (q.log) {
    left.append(card("Task queue", q.running ? badge("working") : badge(q.running === false ? "idle" : "unknown"),
      q.last_result ? h("p", { class: "muted small", text: q.last_result }) : null, logView(q.lines.slice(-18))));
  }

  // approvals + agents + activity
  right.append(card("Awaiting your decision", o.approvals.length ? `${o.approvals.length}` : null,
    o.approvals.length ? h("div", { class: "list" }, o.approvals.map((a) => h("div", { class: "item" },
      badge(a.gate, "plain"), h("div", {}, h("a", { href: `#/approvals/${a.id}`, text: a.id }), " ", h("span", { class: "muted", text: a.summary })), time(a.at))))
      : h("div", { class: "empty", text: "Nothing waiting. Gates that need a review appear here." })));
  right.append(card("Agents", h("a", { href: "#/agents", text: "All →" }), h("div", { class: "list" }, o.agents.filter((a) => a.stages.length || a.calls).map((a) => h("div", { class: "item" },
    avatar(a),
    h("div", {}, h("b", { text: a.title }), h("div", { class: "agent-meta", text: agentModel(a) })),
    badge(a.status === "blocked" ? a.error_kind : a.status))))));
  right.append(card("Recent activity", h("a", { href: "#/activity", text: "All →" }), feed(o.activity)));
  out.append(h("div", { class: "grid two" }, left, right));
  return out;
};

function feed(events) {
  return h("div", { class: "list feed" }, events.map((e) => h("div", { class: "item" },
    h("span", { class: "type-pill", text: e.type }),
    h("div", { class: "what" }, subjectLink(e.subject), " ", h("span", { class: "muted", text: `${e.brief ? `· ${e.brief} ` : ""}by ${e.actor}` })),
    time(e.ts))));
}
function subjectLink(id) {
  if (/^PRJ-/.test(id)) return h("a", { href: `#/projects/${id}`, text: id });
  if (/^APR-/.test(id)) return h("a", { href: `#/approvals/${id}`, text: id });
  if (/^TASK-/.test(id)) return h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); openTask(id); }, text: id });
  return h("span", { class: "mono", text: id });
}

// ---------- projects
const filters = { q: "", state: "all", kind: "all" };
VIEWS.projects = async (r) => {
  if (r.id) return projectDetail(r.id, r.tab);
  const projects = await api("/api/projects");
  const out = h("div", {}, pageHead("Projects", "Every research and engineering project in this lab.",
    h("button", { class: "primary", onclick: newProjectDialog, text: "New project" })));
  const body = h("tbody");
  const search = h("input", { type: "search", placeholder: "Search id, task or text…  ( / )", value: filters.q, "aria-label": "Search projects",
    oninput: (ev) => { filters.q = ev.target.value; draw(); } });
  search.id = "project-search";
  const chip = (group, value, label) => h("button", { class: "chip", "aria-pressed": String(filters[group] === value),
    onclick: (ev) => { filters[group] = value; ev.target.parentElement.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === ev.target))); draw(); }, text: label });
  out.append(h("div", { class: "toolbar" }, search,
    h("div", { class: "chips", role: "group", "aria-label": "State" }, chip("state", "all", "All"), chip("state", "active", "Active"),
      META.research_terminal.map((st) => chip("state", st, human(st)))),
    h("div", { class: "chips", role: "group", "aria-label": "Kind" }, chip("kind", "all", "Any kind"),
      META.project_kinds.map((k) => chip("kind", k.value, human(k.value))))));
  const table = h("table", { class: "table" }, h("thead", {}, h("tr", {}, ["Project", "Task", "Title", "State", "Stage", "Updated"].map((t) => h("th", { text: t })))), body);
  const count = h("p", { class: "muted small" });
  out.append(card(null, null, table, count));
  function draw() {
    const q = filters.q.trim().toLowerCase();
    const rows = projects.filter((p) => (filters.state === "all" || (filters.state === "active" ? !isTerminal(p.state) : p.state === filters.state))
      && (filters.kind === "all" || p.kind === filters.kind)
      && (!q || `${p.id} ${p.key || ""} ${p.objective}`.toLowerCase().includes(q)));
    body.replaceChildren(...rows.map((p) => h("tr", { class: "click", tabindex: "0", onclick: () => go(`/projects/${p.id}`), onkeydown: (ev) => ev.key === "Enter" && go(`/projects/${p.id}`) },
      h("td", {}, h("span", { class: "mono", text: p.id })), h("td", {}, h("span", { class: "mono", text: p.key || "—" })),
      h("td", { class: "title-cell" }, p.title, h("span", { class: "muted", text: p.kind })),
      h("td", {}, badge(p.state)), h("td", {}, p.eng ? badge(p.eng.state) : h("span", { class: "muted", text: "—" })), h("td", {}, time(p.updated_at)))));
    if (!rows.length) body.replaceChildren(h("tr", {}, h("td", { colspan: "6" }, h("div", { class: "empty", text: "No projects match these filters." }))));
    count.textContent = `${rows.length} of ${projects.length} projects`;
  }
  draw();
  return out;
};

async function projectDetail(id, tab) {
  const p = await api(`/api/projects/${encodeURIComponent(id)}`);
  tab = tab || "overview";
  const out = h("div", {});
  out.append(h("div", { class: "crumbs" }, h("a", { href: "#/projects", text: "Projects" }), ` / ${p.id}`));
  const shownTitle = p.key && p.title.startsWith(p.key) ? p.title : `${p.key ? `${p.key} · ` : ""}${p.title}`;
  out.append(pageHead(shownTitle, null, badge(p.state), p.eng ? badge(p.eng.state) : null));
  const tabs = [["overview", "Overview"], ["pipeline", "Pipeline", p.eng_history.length], ["reviews", "Reviews", p.reviews.length],
    ["failures", "Failures", p.failures.length], ["calls", "Agent calls", p.tasks.length], ["events", "Ledger", p.events.length]];
  out.append(h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, label, n]) => h("button", {
    role: "tab", "aria-selected": String(k === tab), onclick: () => go(`/projects/${p.id}/${k}`) }, label, n ? h("span", { class: "n", text: n }) : null))));
  const panel = h("div", { role: "tabpanel" });
  out.append(panel);
  if (tab === "overview") {
    panel.append(h("div", { class: "grid two" },
      h("div", { class: "stack" },
        p.eng ? card("Pipeline", p.eng.id, stepper(p.pipeline, pipelineStep(p.eng.state), isDone(p.state)),
          h("div", { class: "metrics" }, [["Review rounds", p.eng.review_round], ["Patches", p.eng.patch_attempts], ["Redesigns", p.eng.redesigns], ["Test runs", p.eng.test_runs]]
            .map(([l, v]) => h("div", { class: "metric" }, h("b", { text: v }), h("span", { text: l }))))) : null,
        p.halt_reason ? h("div", { class: "alert error" }, h("span", { class: "icon", text: "!" }), h("div", {}, h("div", { class: "title", text: "Halted" }), h("div", { class: "prose small", text: p.halt_reason })), h("span")) : null,
        card("Specification", null, h("div", { class: "prose", text: p.objective })),
        p.origin ? card("Origin", "spawned from an open question", h("p", { class: "small" }, "From ",
          knowledgeLink(p.origin.source), p.origin.conclusion ? [" (after ", knowledgeLink(`lab:${p.origin.lab}/${p.origin.conclusion}`), ")"] : null),
          p.origin.rationale ? h("p", { class: "muted small", text: p.origin.rationale }) : null) : null,
        p.acceptance_criteria.length ? card("Acceptance criteria", null, h("ol", {}, p.acceptance_criteria.map((a) => h("li", { class: "prose", text: a })))) : null),
      h("div", { class: "stack" },
        card("Facts", null, h("div", { class: "list" },
          [["Kind", p.kind], ["Autonomy", p.autonomy_level === undefined || p.autonomy_level === null ? null
            : `${p.autonomy_level} · ${(META.autonomy.levels.find((l) => l.level === p.autonomy_level) || {}).label || ""}`], ["Cycle", p.cycle], ["Created", absTime(p.created_at)], ["Updated", absTime(p.updated_at)], ["Branch", p.eng?.branch], ["Head", p.eng?.head?.slice(0, 12)]]
            .filter(([, v]) => v !== undefined && v !== null && v !== "")
            .map(([k, v]) => h("div", { class: "item" }, h("span", { class: "muted", text: k }), h("span", { class: "mono", text: v }), h("span"))))),
        p.mandate_refs.length ? card("Mandate references", null, h("div", { class: "tags" }, p.mandate_refs.map((m) => h("span", { class: "tag", text: m })))) : null,
        p.deliveries.length ? card("Deliveries", null, h("div", { class: "list" }, p.deliveries.map((d) => h("div", { class: "item" }, badge(META.engineering_pipeline.at(-1)), h("span", { class: "mono", text: `${d.id} · ${String(d.commit).slice(0, 12)}` }), time(d.at))))) : null,
        p.approvals.length ? card("Gate decisions", null, h("div", { class: "list" }, p.approvals.map((a) => h("div", { class: "item" }, badge(a.status), h("div", {}, h("a", { href: `#/approvals/${a.id}`, text: `${a.id} · ${a.gate}` }), h("div", { class: "muted small", text: a.decided_by ? `by ${a.decided_by}` : "" })), time(a.at))))) : null)));
  } else if (tab === "pipeline") {
    panel.append(card("Engineering transitions", null, p.eng_history.length ? h("ol", { class: "timeline" }, p.eng_history.slice().reverse().map((t) => h("li", {
      class: { ok: "ok", bad: "bad", warn: "bad" }[META.tones[t.to]] || "" },
      h("div", { class: "t", text: `${human(t.from)} → ${human(t.to)}` }), h("div", { class: "r", text: `${t.eng} · ${t.reason || ""}` })))) : h("div", { class: "empty", text: "No transitions yet." })));
  } else if (tab === "reviews") {
    panel.append(p.reviews.length ? h("div", { class: "stack" }, p.reviews.map((r) => card(`${r.id} · round ${r.round ?? "?"}`, h("span", { class: "row" }, badge(r.verdict), time(r.at)),
      h("p", { class: "muted small", text: `${human(r.type)} · commit ${String(r.commit || "").slice(0, 12)} · tests ${r.tests_passed ? "passed" : "not passed"}` }),
      (r.findings || []).length ? r.findings.map(findingView) : h("p", { class: "muted", text: "No findings." }))))
      : h("div", { class: "empty", text: "No reviews yet." }));
  } else if (tab === "failures") {
    panel.append(card(null, null, p.failures.length ? h("div", { class: "list" }, p.failures.map((f) => h("div", { class: "item" },
      badge(f.category), h("div", { class: "prose small", text: f.summary }), time(f.at)))) : h("div", { class: "empty", text: "No failures recorded." })));
  } else if (tab === "calls") {
    panel.append(card(null, null, p.tasks.length ? h("table", { class: "table" }, h("thead", {}, h("tr", {}, ["Call", "Agent", "Role", "Stage", "Outcome", "When"].map((t) => h("th", { text: t })))),
      h("tbody", {}, p.tasks.map((t) => h("tr", { class: "click", tabindex: "0", onclick: () => openTask(t.id), onkeydown: (ev) => ev.key === "Enter" && openTask(t.id) },
        h("td", {}, h("span", { class: "mono", text: t.id })), h("td", {}, h("span", { text: t.agent }), t.model ? h("span", { class: "muted small", text: ` · ${t.model}` }) : null),
        h("td", { text: t.role }), h("td", { text: human(t.stage) }),
        h("td", {}, badge(t.error_kind || t.status)), h("td", {}, time(t.at)))))) : h("div", { class: "empty", text: "No agent calls yet." })));
  } else if (tab === "events") {
    panel.append(card(null, null, feed(p.events.slice().reverse().map((e) => ({ ...e, brief: (e.data && (e.data.reason || (e.data.to && `${e.data.from} → ${e.data.to}`) || e.data.stage)) || "" })))));
  }
  return out;
}

function findingView(f) {
  if (typeof f === "string") return h("div", { class: "finding" }, h("div", { class: "prose", text: f }));
  const sev = String(f.severity || f.level || "note").toLowerCase();
  return h("div", { class: `finding ${sev}` },
    h("div", { class: "row start wrap" }, h("span", { class: `badge ${sev === "critical" || sev === "major" ? "b-bad" : sev === "minor" ? "b-warn" : "b-info"}`, text: sev })),
    h("div", { class: "prose", text: f.description || f.summary || JSON.stringify(f) }),
    f.location || f.file ? h("div", { class: "loc", text: f.location || f.file }) : null);
}

// ---------- approvals
VIEWS.approvals = async (r) => {
  if (r.id) return approvalDetail(r.id);
  const list = await api("/api/approvals");
  const out = h("div", {}, pageHead("Approvals", "Review gates waiting for a decision. Decisions made here are recorded in the ledger as yours."));
  out.append(list.length ? h("div", { class: "grid cards" }, list.map((a) => h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { text: a.id }), badge("pending")),
    h("p", { text: a.summary }), h("div", { class: "tags" }, badge(a.gate, "plain"), a.project ? h("a", { href: `#/projects/${a.project}`, class: "tag", text: a.project }) : null),
    h("p", { class: "muted small", text: `${(a.files || []).length} file(s) · requested ${ago(a.at)}` }),
    h("button", { class: "primary", onclick: () => go(`/approvals/${a.id}`), text: "Review" }))))
    : h("div", { class: "empty", text: "No approvals waiting. When the lab reaches a safety or contracts gate, it appears here." }));
  return out;
};

function parseDiff(text) {
  const files = [];
  let cur = null;
  for (const line of String(text || "").split("\n")) {
    const m = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
    if (m) { cur = { name: m[2], lines: [], add: 0, del: 0 }; files.push(cur); continue; }
    if (!cur) { cur = { name: "(diff)", lines: [], add: 0, del: 0 }; files.push(cur); }
    if (line.startsWith("+") && !line.startsWith("+++")) cur.add++;
    else if (line.startsWith("-") && !line.startsWith("---")) cur.del++;
    cur.lines.push(line);
  }
  return files;
}
function diffView(text) {
  const files = parseDiff(text);
  if (!files.length) return h("div", { class: "empty", text: "No diff stored for this approval." });
  return h("div", {}, files.map((f, i) => h("details", { class: "diff-file", open: i < 3 },
    h("summary", {}, h("span", { text: f.name }), h("span", { class: "stat" }, h("span", { class: "a", text: `+${f.add}` }), " ", h("span", { class: "d", text: `−${f.del}` }))),
    h("pre", { class: "diff" }, f.lines.map((ln) => h("span", {
      class: `ln ${ln.startsWith("@@") ? "hunk" : ln.startsWith("+") && !ln.startsWith("+++") ? "add" : ln.startsWith("-") && !ln.startsWith("---") ? "del" : /^(index|\+\+\+|---|new file|deleted file)/.test(ln) ? "meta" : ""}`,
      text: ln || " " }))))));
}

async function approvalDetail(id) {
  const a = await api(`/api/approvals/${encodeURIComponent(id)}`);
  const out = h("div", {});
  out.append(h("div", { class: "crumbs" }, h("a", { href: "#/approvals", text: "Approvals" }), ` / ${a.id}`));
  out.append(pageHead(`${a.id} · ${a.gate}`, a.summary, badge(a.status)));
  const left = h("div", { class: "stack" }, card("Changes under review", `${(a.files || []).length} file(s)`, diffView(a.diff)));
  const right = h("div", { class: "stack" });
  right.append(card("Context", null, h("div", { class: "list" },
    [["Subject", a.subject], ["Project", a.project], ["Requested", absTime(a.at)]].filter(([, v]) => v).map(([k, v]) =>
      h("div", { class: "item" }, h("span", { class: "muted", text: k }), k === "Project" ? h("a", { href: `#/projects/${v}`, text: v }) : h("span", { class: "mono", text: v }), h("span")))),
    (a.files || []).length ? h("div", { class: "tags" }, a.files.map((f) => h("span", { class: "tag mono", text: f }))) : null));
  if (a.status === "pending") {
    const note = h("textarea", { id: "decision-note", placeholder: "What did you check? (required; stored in the ledger)", maxlength: "2000", required: true });
    const decide = async (approved) => {
      if (!note.value.trim()) { note.focus(); toast("Add a note saying what you checked.", "bad"); return; }
      const ok = await confirmDialog(approved ? "Approve this gate?" : "Reject this gate?",
        `${a.id} will be recorded as ${approved ? "approved" : "rejected"} by you (the human) in the tamper-evident ledger. This cannot be undone.`,
        approved ? "Approve" : "Reject", approved ? "ok" : "bad");
      if (!ok) return;
      try { const res = await api(`/api/approvals/${encodeURIComponent(a.id)}`, { method: "POST", body: { approved, note: note.value } });
        toast(`${res.id} ${res.status}`, "ok"); go("/approvals"); } catch (err) { toast(err.message, "bad"); }
    };
    right.append(card("Your decision", null, h("label", {}, "Review note", note),
      h("p", { class: "muted small", text: "Recorded as decided_by = human. The lab resumes the next time its queue runs." }),
      h("div", { class: "actions" }, h("button", { class: "ok", onclick: () => decide(true), text: "Approve" }), h("button", { class: "bad", onclick: () => decide(false), text: "Reject" }))));
  } else {
    right.append(card("Decision", null, h("p", {}, badge(a.status), ` by ${a.decided_by || "?"}`), a.note ? h("div", { class: "prose small", text: a.note }) : null));
  }
  out.append(h("div", { class: "grid two" }, left, right));
  return out;
}

// ---------- agents
function avatar(a) {
  const label = (a.title || a.name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return h("div", { class: `avatar av-${a.role || "custom"}`, text: label, "aria-hidden": "true" });
}
const agentModel = (a) => `${a.backend || "no backend"} · ${a.model || "default model"}${a.backup_backend ? ` (backup ${a.backup_backend}${a.backup_model ? ` · ${a.backup_model}` : ""})` : ""}`;
const stageLabel = (name) => (META.stages.find((s) => s.name === name) || { label: human(name) }).label;

VIEWS.agents = async () => {
  const [agents, reg] = await Promise.all([api("/api/agents"), api("/api/registry")]);
  const out = h("div", {}, pageHead("Agents", "Any backend and model can do any stage; each stage's role fixes what it may read or write.",
    h("button", { onclick: () => applyPreset(), text: "Create organisation preset" }),
    h("button", { class: "primary", onclick: () => agentDialog(null, reg), text: "New agent" })));
  if (reg.problems.length) out.append(h("div", { class: "alerts" }, reg.problems.map((pr) => alertBox({ level: "error", title: "Configuration problem", detail: pr }))));
  out.append(h("div", { class: "grid cards" }, agents.map((a) => h("section", { class: "card" },
    h("div", { class: "agent-top" }, avatar(a),
      h("div", {}, h("h2", { text: a.title }), h("div", { class: "agent-meta", text: `${a.name} · ${agentModel(a)}` })),
      h("div", { class: "actions" }, badge(a.status === "blocked" ? a.error_kind : a.status))),
    a.charter ? h("p", { class: "prose small", text: a.charter }) : null,
    h("div", { class: "tags" }, a.stages.length ? a.stages.map((st) => h("span", { class: "tag", text: stageLabel(st) })) : h("span", { class: "muted small", text: "Not allocated to any stage" })),
    h("div", { class: "metrics" }, [["Calls", a.calls], ["Completed", a.completed], ["Errors", a.errors]].map(([l, v]) => h("div", { class: "metric" }, h("b", { text: v }), h("span", { text: l })))),
    h("div", { class: "spark", "aria-label": "Recent calls, oldest to newest" }, a.recent.slice().reverse().map((t) => h("span", { class: `s-${t.status} k-${t.error_kind || ""}`, title: `${t.id} · ${t.stage} · ${t.error_kind || t.status} · ${absTime(t.at)}` }))),
    a.active ? h("p", { class: "small" }, "Working on ", subjectLink(a.active.task), ` (${human(a.active.stage)}) since ${ago(a.active.since)}`) : null,
    a.error_message ? h("div", { class: `alert ${a.error_kind === "usage_limit" || a.error_kind === "network" ? "warn" : "error"}` },
      h("span", { class: "icon", text: "!" }), h("div", {}, h("div", { class: "title", text: `Last call failed · ${human(a.error_kind)}` }), h("div", { class: "prose small", text: a.error_message })), h("span")) : null,
    a.error ? h("details", {}, h("summary", { class: "small muted", text: "Raw error" }), h("pre", { class: "code", text: a.error })) : null,
    a.last_task ? h("p", { class: "muted small" }, "Last call ", subjectLink(a.last_task.id), ` · ${human(a.last_task.stage)} · ${ago(a.last_task.at)}`) : null,
    h("div", { class: "actions" }, h("button", { class: "small", onclick: () => agentDialog(a, reg), text: "Edit" }),
      a.default_for_role ? null : h("button", { class: "small ghost", onclick: () => removeAgent(a), text: "Remove" }))))));
  out.append(allocationCard(reg));
  return out;
};

function allocationCard(reg) {
  const names = Object.keys(reg.agents).sort();
  const pending = {};
  const backendOf = (n) => META.backends.find((b) => b.name === (reg.agents[n] || {}).backend) || {};
  const rows = META.planes.map((plane) => [h("tr", { class: "group" }, h("th", { colspan: "4", text: human(plane) })),
    META.stages.filter((st) => st.plane === plane).map((st) => {
      const current = reg.allocation[st.name] || "";
      const select = h("select", { "aria-label": `Agent for ${st.label}`, onchange: (ev) => { pending[st.name] = ev.target.value; save.disabled = false; } },
        h("option", { value: "", text: `Role default (${st.role})`, selected: current === "" }),
        names.map((n) => {
          const unfit = st.writable && !backendOf(n).tools;
          return h("option", { value: n, selected: current === n, disabled: unfit,
            text: `${reg.agents[n].title || n} · ${reg.agents[n].backend || "?"}${reg.agents[n].model ? ` · ${reg.agents[n].model}` : ""}${unfit ? " (cannot write files)" : ""}` });
        }));
      return h("tr", {}, h("td", {}, h("b", { text: st.label }), h("div", { class: "muted small mono", text: st.name })),
        h("td", {}, badge(st.role, "plain"), st.writable ? h("span", { class: "muted small", text: " writes files" }) : st.reads_files ? h("span", { class: "muted small", text: " reads files" }) : null),
        h("td", {}, select), h("td", { class: "muted small", text: reg.effective[st.name] }));
    })]);
  const save = h("button", { class: "primary", disabled: true, text: "Save allocation", onclick: async () => {
    try { await api("/api/allocation", { method: "POST", body: { allocation: pending } }); toast("Allocation saved; it applies from the next agent call", "ok"); render(); }
    catch (err) { toast(err.message, "bad"); }
  } });
  return card("Stage allocation", h("span", { class: "row" }, h("span", { class: "sub", text: reg.file || "" }), save),
    h("p", { class: "muted small", text: "Choose which agent performs each stage of the research and engineering process. Permissions (read-only, writable worktree, tests only) stay with the stage's role." }),
    h("table", { class: "table alloc" }, h("thead", {}, h("tr", {}, ["Stage", "Role", "Agent", "Effective"].map((t) => h("th", { text: t })))), h("tbody", {}, rows)));
}

function agentDialog(a, reg) {
  const m = $("modal");
  const spec = (a && a.spec) || {};
  const field = (id, label, el, hint) => h("label", {}, label, hint ? h("span", { class: "hint", text: hint }) : null, el);
  const name = h("input", { id: "ag-name", value: a ? a.name : "", placeholder: "lowercase_name", disabled: !!a, required: true });
  const title = h("input", { id: "ag-title", value: spec.title || "", placeholder: "Display name" });
  const backendSel = (id, value, allowEmpty) => h("select", { id }, allowEmpty ? h("option", { value: "", text: "None" }) : null,
    META.backends.map((b) => h("option", { value: b.name, selected: b.name === value, text: b.label })));
  const backend = backendSel("ag-backend", spec.backend || (META.backends[0] || {}).name, false);
  const models = h("datalist", { id: "ag-models" }, (reg.known_models || []).map((mm) => h("option", { value: mm })));
  const model = h("input", { id: "ag-model", value: spec.model || "", list: "ag-models", placeholder: "Backend default" });
  const effort = h("input", { id: "ag-effort", value: spec.effort || "", placeholder: "Optional (backends that support it)" });
  const timeout = h("input", { id: "ag-timeout", type: "number", min: "1", value: spec.timeout ?? "", placeholder: "Backend default (s)" });
  const charter = h("textarea", { id: "ag-charter", maxlength: "4000", placeholder: "What this agent focuses on (added to its role's charter)", text: spec.charter || "" });
  const backup = backendSel("ag-backup", spec.backup_backend || "", true);
  const backupModel = h("input", { id: "ag-backup-model", value: spec.backup_model || "", list: "ag-models", placeholder: "Backup model" });
  const submit = async () => {
    const body = { spec: { ...Object.fromEntries(Object.entries(spec).filter(([k]) => !["title", "backend", "model", "effort", "timeout", "charter", "backup_backend", "backup_model"].includes(k))),
      title: title.value.trim(), backend: backend.value, model: model.value.trim(), effort: effort.value.trim(),
      timeout: timeout.value ? Number(timeout.value) : null, charter: charter.value.trim(), backup_backend: backup.value, backup_model: backupModel.value.trim() } };
    try { await api(`/api/agents/${encodeURIComponent(name.value.trim())}`, { method: "POST", body }); m.close(); toast("Agent saved", "ok"); render(); }
    catch (err) { toast(err.message, "bad"); }
  };
  m.replaceChildren(h("div", { class: "modal-body" }, h("h2", { text: a ? `Edit ${a.title}` : "New agent" }), models,
    h("div", { class: "form-grid" }, field("ag-name", "Name", name, "Used in agents.toml and the ledger"), field("ag-title", "Title", title),
      field("ag-backend", "Backend", backend), field("ag-model", "Model", model, "Any model id the backend accepts"),
      field("ag-effort", "Effort", effort), field("ag-timeout", "Timeout (s)", timeout),
      field("ag-backup", "Backup backend", backup, "Used automatically on usage limits"), field("ag-backup-model", "Backup model", backupModel)),
    field("ag-charter", "Charter", charter)),
    h("div", { class: "modal-actions" }, h("button", { onclick: () => m.close(), text: "Cancel" }), h("button", { class: "primary", onclick: submit, text: "Save agent" })));
  m.showModal();
  (a ? title : name).focus();
}

async function removeAgent(a) {
  if (!(await confirmDialog(`Remove ${a.title}?`, "Stages allocated to it must be reallocated first. Its past calls stay in the ledger.", "Remove", "bad"))) return;
  try { await api(`/api/agents/${encodeURIComponent(a.name)}/remove`, { method: "POST", body: {} }); toast("Agent removed", "ok"); render(); }
  catch (err) { toast(err.message, "bad"); }
}

async function applyPreset() {
  const preset = META.presets[0];
  if (!preset) return;
  const list = preset.agents.map((x) => x.title).join(", ");
  if (!(await confirmDialog("Create the research and engineering organisation?", `Creates or updates: ${list}. Each starts on its role's current backend and model; change them per agent afterwards.`, "Create", "primary"))) return;
  try { const res = await api("/api/agents/preset", { method: "POST", body: { name: preset.name } }); toast(`${res.created.length} agents ready`, "ok"); render(); }
  catch (err) { toast(err.message, "bad"); }
}

// ---------- programmes (D54): hierarchical coordination
VIEWS.programmes = async (r) => {
  if (r.id) return programmeDetail(r.id);
  const list = await api("/api/programmes");
  $("nav-programmes").textContent = list.filter((p) => !META.programme_terminal.includes(p.state)).length || "";
  const out = h("div", {}, pageHead("Programmes", "Objectives too large for one project: the Research Director plans and reviews them, the Engineering Director splits engineering work into specialty tasks.",
    h("button", { class: "primary", onclick: newProgrammeDialog, text: "New programme" })));
  out.append(card(null, null, list.length ? h("table", { class: "table" },
    h("thead", {}, h("tr", {}, ["Programme", "Objective", "State", "Items", "Reviews", "Updated"].map((t) => h("th", { text: t })))),
    h("tbody", {}, list.map((p) => h("tr", { class: "click", tabindex: "0", onclick: () => go(`/programmes/${p.id}`), onkeydown: (ev) => ev.key === "Enter" && go(`/programmes/${p.id}`) },
      h("td", {}, h("span", { class: "mono", text: p.id })), h("td", { class: "title-cell" }, p.title),
      h("td", {}, badge(p.state)), h("td", {}, Object.entries(p.status_counts).map(([s, n]) => h("span", { class: "muted small", text: `${n} ${s} ` }))),
      h("td", { text: p.reviews }), h("td", {}, time(p.updated_at)))))) : h("div", { class: "empty", text: "No programmes yet. Create one, then run it with `autolab programme LAB run PRG-…`." })));
  return out;
};

async function programmeDetail(id) {
  const p = await api(`/api/programmes/${encodeURIComponent(id)}`);
  const out = h("div", {});
  out.append(h("div", { class: "crumbs" }, h("a", { href: "#/programmes", text: "Programmes" }), ` / ${p.id}`));
  out.append(pageHead(p.title, null, badge(p.state)));
  if (p.halt_reason) out.append(h("div", { class: "alerts" }, alertBox({ level: "error", title: "Halted: needs a human", detail: p.halt_reason })));
  if (p.blocked_on) out.append(h("div", { class: "alerts" }, alertBox({ level: "warn", title: `Waiting on ${p.blocked_on}`, detail: "A project in this programme needs a human decision; the programme continues when it is resolved." })));
  const tree = h("div", { class: "list" }, p.items.map((it) => {
    const latest = it.latest || {};
    return h("div", { class: `item ${it.parent ? "child" : ""}` },
      h("div", {}, badge(it.kind, "plain"), it.specialty ? h("span", { class: "tag", text: it.specialty }) : null),
      h("div", {}, h("b", { class: "mono", text: it.key }), " ", h("span", { class: "prose small", text: it.objective }),
        it.depends_on.length ? h("div", { class: "muted small", text: `after ${it.depends_on.join(", ")}` }) : null,
        it.projects.length ? h("div", { class: "small" }, it.projects.map((pid) => [h("a", { href: `#/projects/${pid}`, class: "mono", text: pid }), " "]),
          latest.conclusions ? latest.conclusions.map((c) => [badge(c.outcome), " "]) : null,
          latest.delivery ? h("span", { class: "muted", text: `delivered ${String(latest.delivery.commit || "").slice(0, 10)}` }) : null) : null,
        it.drop_reason ? h("div", { class: "muted small", text: `dropped: ${it.drop_reason}` }) : null,
        it.architecture_notes ? h("details", {}, h("summary", { class: "small muted", text: "Engineering Director's notes" }), h("div", { class: "prose small", text: it.architecture_notes })) : null),
      badge(it.status));
  }));
  const decisions = h("ol", { class: "timeline" }, p.decisions.slice().reverse().map((x) => h("li", { class: x.decision === "complete" ? "ok" : x.decision === "escalate" ? "bad" : "" },
    h("div", { class: "t", text: `${human(x.stage)}${x.decision ? ` · ${x.decision}` : ""}` }),
    h("div", { class: "r", text: x.assessment || x.summary || "" }),
    (x.blockers || []).length ? h("div", { class: "r", text: `blockers: ${x.blockers.join("; ")}` }) : null,
    x.dropped && Object.keys(x.dropped).length ? h("div", { class: "r", text: `dropped: ${Object.entries(x.dropped).map(([k, v]) => `${k} (${v})`).join("; ")}` }) : null)));
  out.append(h("div", { class: "grid two" },
    h("div", { class: "stack" }, card("Work items", "Research Director → items; Engineering Director → specialty tasks", tree)),
    h("div", { class: "stack" },
      card("Objective", null, h("div", { class: "prose", text: p.objective }), p.plan_summary ? h("p", { class: "muted small", text: p.plan_summary }) : null,
        p.success_criteria.length ? h("ul", {}, p.success_criteria.map((c) => h("li", { class: "small", text: c }))) : null),
      card("Director decisions", `${p.reviews} review(s)`, p.decisions.length ? decisions : h("div", { class: "empty", text: "Not planned yet. Run the programme." })),
      card("Director calls", null, p.director_calls.length ? h("div", { class: "list" }, p.director_calls.map((t) => h("div", { class: "item" },
        subjectLink(t.id), h("span", { class: "small", text: `${human(t.stage)} · ${t.agent || ""}` }), badge(t.status)))) : h("div", { class: "empty", text: "None yet." })))));
  return out;
}

function newProgrammeDialog() {
  const m = $("modal");
  const objective = h("textarea", { id: "pg-objective", maxlength: "4000", placeholder: "The research and engineering objective", required: true });
  const refs = h("input", { id: "pg-refs", placeholder: `${META.ui.milestone_label || "Milestone"} 2, REQ-…` });
  const submit = async () => {
    try { const res = await api("/api/programmes", { method: "POST", body: { objective: objective.value, refs: refs.value.split(",").map((x) => x.trim()).filter(Boolean) } });
      m.close(); toast(`${res.id} created`, "ok"); go(`/programmes/${res.id}`); }
    catch (err) { toast(err.message, "bad"); }
  };
  m.replaceChildren(h("div", { class: "modal-body" }, h("h2", { text: "New programme" }),
    h("p", { class: "muted small", text: "Creates the programme in the ledger. Run it with `autolab programme LAB run PRG-…`; the Research Director plans it on the first step." }),
    h("label", {}, "Objective", objective), h("label", {}, "Mandate references", h("span", { class: "hint", text: "Optional, comma-separated" }), refs)),
    h("div", { class: "modal-actions" }, h("button", { onclick: () => m.close(), text: "Cancel" }), h("button", { class: "primary", onclick: submit, text: "Create programme" })));
  m.showModal();
  objective.focus();
}

// ---------- knowledge (K1)
function knowledgeLink(source) {
  return h("a", { href: "#", class: "mono", text: source.replace(/^lab:/, ""), onclick: (ev) => { ev.preventDefault(); openNode(source); } });
}
function nodeRow(n) {
  return h("div", { class: "item" }, badge(n.entity || n.kind, "plain"),
    h("div", {}, knowledgeLink(n.source), n.status ? [" ", badge(n.status)] : null, n.label ? h("span", { class: "muted small", text: ` ${n.label}` }) : null,
      h("div", { class: "prose small", text: n.text })),
    n.score !== undefined ? h("span", { class: "muted small mono", text: n.score.toFixed(2) }) : time(n.created_at));
}
VIEWS.knowledge = async () => {
  const k = await api("/api/knowledge");
  const st = k.stats;
  $("nav-knowledge").textContent = st.open_questions || "";
  const out = h("div", {}, pageHead("Knowledge", `What the lab has learned, across ${st.labs.length === 1 ? "this lab" : `${st.labs.length} labs (${st.labs.join(", ")})`}: results, failures, methods and open questions, each traceable to its records.`));
  if (k.problems.length) out.append(h("div", { class: "alerts" }, k.problems.map((pr) => alertBox({ level: "warn", title: "Included lab unavailable", detail: pr }))));
  out.append(h("div", { class: "grid kpis" }, kpi("Knowledge records", st.nodes), kpi("Links", st.edges),
    kpi("Conclusions", st.by_kind.conclusion || 0), kpi("Failures kept", st.by_kind.failure || 0), kpi("Open questions", st.open_questions, st.open_questions ? "attn" : "")));
  // search
  const results = h("div", { class: "list" });
  const kindSel = h("select", { "aria-label": "Record kind" }, h("option", { value: "", text: "All kinds" }), k.kinds.map((x) => h("option", { value: x, text: human(x) })));
  kindSel.style.maxWidth = "200px";
  const box = h("input", { type: "search", id: "knowledge-search", placeholder: "Search what the lab knows…", "aria-label": "Search knowledge" });
  let timer = null;
  const run = async () => {
    const q = box.value.trim();
    if (!q) { results.replaceChildren(h("div", { class: "empty", text: "Type to search conclusions, failures, methods, hypotheses and deliveries." })); return; }
    const params = new URLSearchParams({ q }); if (kindSel.value) params.append("kind", kindSel.value);
    try { const hits = await api(`/api/knowledge/search?${params}`);
      results.replaceChildren(...(hits.length ? hits.map(nodeRow) : [h("div", { class: "empty", text: "Nothing matches. Retrieval is lexical: try the words the records use." })])); }
    catch (err) { results.replaceChildren(h("div", { class: "empty", text: err.message })); }
  };
  box.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 250); });
  kindSel.addEventListener("change", run);
  run();
  const left = h("div", { class: "stack" }, card("Search", null, h("div", { class: "toolbar" }, box, kindSel), results),
    card("Conclusions", null, k.conclusions.length ? h("div", { class: "list" }, k.conclusions.map(nodeRow)) : h("div", { class: "empty", text: "No conclusions yet." })));
  const right = h("div", { class: "stack" }, card("Open questions", "results that raised new research",
    k.open_questions.length ? h("div", { class: "list" }, k.open_questions.map((q) => h("div", { class: "item" },
      h("span", { class: "badge plain", text: `p${q.priority ?? "-"}` }),
      h("div", {}, h("div", { class: "prose small", text: q.question }), h("div", { class: "muted small" }, knowledgeLink(q.source), q.project ? ` · ${q.project}` : "")),
      h("button", { class: "small", onclick: () => spawnProject(q), text: "Start project" }))))
      : h("div", { class: "empty", text: "No open questions. They appear when a research cycle ends." })),
    card("Entities", null, h("div", { class: "list" }, Object.entries(st.by_entity || st.by_kind).map(([kind, n]) => h("div", { class: "item" }, badge(kind, "plain"), h("span", { text: "" }), h("b", { text: n }))))),
    card("Relationships", null, h("div", { class: "list" }, Object.entries(st.by_relation || {}).map(([rel, n]) => h("div", { class: "item" }, h("span", { class: "mono", text: rel }), h("span", { text: "" }), h("b", { text: n }))))));
  out.append(h("div", { class: "grid two" }, left, right));
  return out;
};
async function spawnProject(q) {
  if (!(await confirmDialog("Start a research project from this question?", q.question, "Start project", "primary"))) return;
  try { const res = await api("/api/knowledge/spawn", { method: "POST", body: { source: q.source } }); toast(`${res.id} created`, "ok"); go(`/projects/${res.id}`); }
  catch (err) { toast(err.message, "bad"); }
}
async function openNode(source) {
  const drawer = $("drawer");
  drawer.hidden = false;
  drawer.replaceChildren(skeleton());
  try {
    const n = await api(`/api/knowledge/node?id=${encodeURIComponent(source)}`);
    const rel = (list, dir) => list.length ? h("div", { class: "list" }, list.map((e) => h("div", { class: "item" },
      h("span", { class: "muted small mono", text: dir === "out" ? `${e.relation} →` : `← ${e.relation}` }),
      h("div", {}, knowledgeLink(e.source), " ", badge(e.kind, "plain"), h("div", { class: "prose small", text: e.text })), h("span")))) : h("p", { class: "muted small", text: "None." });
    drawer.replaceChildren(
      h("div", { class: "row" }, h("h2", { text: `${n.source.replace(/^lab:/, "")} · ${human(n.kind)}` }), h("button", { class: "ghost", onclick: closeDrawer, "aria-label": "Close", text: "✕" })),
      h("div", { class: "row start wrap" }, n.status ? badge(n.status) : null, n.label ? h("span", { class: "agent-meta", text: n.label }) : null, n.project ? h("span", { class: "muted small", text: n.project }) : null, time(n.created_at)),
      card("Content", null, h("div", { class: "prose", text: n.text })),
      card("Derived from", null, rel(n.out, "out")), card("Led to", null, rel(n.in, "in")));
    drawer.querySelector("button")?.focus();
  } catch (err) { drawer.replaceChildren(h("p", { text: err.message }), h("button", { onclick: closeDrawer, text: "Close" })); }
}

// ---------- activity
VIEWS.activity = async () => {
  const events = await api("/api/activity?limit=300");
  const types = [...new Set(events.map((e) => e.type))].sort();
  const out = h("div", {}, pageHead("Activity", "The lab's tamper-evident ledger, newest first."));
  let chosen = "all";
  const list = h("div");
  const draw = () => list.replaceChildren(feed(events.filter((e) => chosen === "all" || e.type === chosen)));
  const select = h("select", { "aria-label": "Event type", onchange: (ev) => { chosen = ev.target.value; draw(); } },
    h("option", { value: "all", text: "All event types" }), types.map((t) => h("option", { value: t, text: t })));
  select.style.maxWidth = "260px";
  out.append(h("div", { class: "toolbar" }, select), card(null, null, list));
  draw();
  return out;
};

// ------------------------------------------------------------------ drawers & dialogs
async function openTask(id) {
  const drawer = $("drawer");
  drawer.hidden = false;
  drawer.replaceChildren(skeleton());
  try {
    const t = await api(`/api/tasks/${encodeURIComponent(id)}`);
    const r = t.result || {};
    drawer.replaceChildren(
      h("div", { class: "row" }, h("h2", { text: `${t.id} · ${t.packet.role} · ${human(t.packet.stage)}` }), h("button", { class: "ghost", onclick: closeDrawer, "aria-label": "Close", text: "✕" })),
      h("div", { class: "row start wrap" }, badge(r.error_kind || r.status), r.backend ? h("span", { class: "agent-meta", text: `${r.agent ? `${r.agent} · ` : ""}${r.backend.backend || ""} ${r.backend.model || ""}` }) : null, r.attempts ? h("span", { class: "muted small", text: `${r.attempts} attempt(s)` }) : null),
      r.summary ? card("Summary", null, h("div", { class: "prose", text: r.summary })) : null,
      r.error ? card("Error", null, h("pre", { class: "code", text: r.error })) : null,
      (r.rejections || []).length ? card("Protocol rejections", null, h("pre", { class: "code", text: r.rejections.join("\n\n") })) : null,
      card("Task packet", null, h("pre", { class: "code", text: JSON.stringify(t.packet, null, 2) })),
      t.completion ? card("Validated completion", null, h("pre", { class: "code", text: JSON.stringify(t.completion, null, 2) })) : null);
    drawer.querySelector("button")?.focus();
  } catch (err) { drawer.replaceChildren(h("p", { text: err.message }), h("button", { onclick: closeDrawer, text: "Close" })); }
}
function closeDrawer() { $("drawer").hidden = true; }

function confirmDialog(title, body, okLabel, okClass) {
  return new Promise((resolve) => {
    const m = $("modal");
    const done = (v) => { m.close(); resolve(v); };
    m.replaceChildren(h("div", { class: "modal-body" }, h("h2", { text: title }), h("p", { class: "muted", text: body })),
      h("div", { class: "modal-actions" }, h("button", { onclick: () => done(false), text: "Cancel" }), h("button", { class: okClass, onclick: () => done(true), text: okLabel })));
    m.onclose = () => resolve(false);
    m.showModal();
  });
}

function newProjectDialog() {
  const m = $("modal");
  const kinds = META.project_kinds;
  const needsAcceptance = (v) => (kinds.find((k) => k.value === v) || {}).needs_acceptance;
  const kind = h("select", { id: "np-kind" }, kinds.map((k) => h("option", { value: k.value, text: k.label })));
  const objective = h("textarea", { id: "np-objective", maxlength: "4000", placeholder: "e.g. Investigate whether X can produce Y", required: true });
  const accept = h("textarea", { id: "np-accept", placeholder: "One criterion per line" });
  const acceptWrap = h("label", {}, "Acceptance criteria", h("span", { class: "hint", text: "Engineering projects need at least one." }), accept);
  acceptWrap.hidden = !needsAcceptance(kind.value);
  const refs = h("input", { id: "np-refs", placeholder: `${META.ui.milestone_label || "Milestone"} 2, REQ-…` });
  kind.addEventListener("change", () => { acceptWrap.hidden = !needsAcceptance(kind.value); });
  const submit = async () => {
    const body = { kind: kind.value, objective: objective.value, refs: refs.value.split(",").map((x) => x.trim()).filter(Boolean) };
    if (needsAcceptance(kind.value)) body.acceptance = accept.value.split("\n").map((x) => x.trim()).filter(Boolean);
    try { const res = await api("/api/projects", { method: "POST", body }); m.close(); toast(`${res.id} created`, "ok"); go(`/projects/${res.id}`); }
    catch (err) { toast(err.message, "bad"); }
  };
  m.replaceChildren(h("div", { class: "modal-body" }, h("h2", { text: "New project" }),
    h("p", { class: "muted small", text: "Creates the project in the ledger. Run it with `autolab run` or a queue; the dashboard does not start agents." }),
    h("label", {}, "Type", kind), h("label", {}, "Objective", objective), acceptWrap, h("label", {}, "Mandate references", h("span", { class: "hint", text: "Optional, comma-separated" }), refs)),
    h("div", { class: "modal-actions" }, h("button", { onclick: () => m.close(), text: "Cancel" }), h("button", { class: "primary", onclick: submit, text: "Create project" })));
  m.showModal();
  objective.focus();
}

// ------------------------------------------------------------------ command palette
let paletteItems = [], paletteIndex = 0;
async function openPalette() {
  const dlg = $("palette"), input = $("palette-input");
  const projects = store.projects || (store.projects = await api("/api/projects").catch(() => []));
  const base = [
    { label: "Overview", kind: "view", run: () => go("/overview") }, { label: "Projects", kind: "view", run: () => go("/projects") },
    { label: "Approvals", kind: "view", run: () => go("/approvals") }, { label: "Agents", kind: "view", run: () => go("/agents") },
    { label: "Activity", kind: "view", run: () => go("/activity") }, { label: "Knowledge", kind: "view", run: () => go("/knowledge") },
    { label: "Programmes", kind: "view", run: () => go("/programmes") }, { label: "New programme…", kind: "command", run: newProgrammeDialog }, { label: "New project…", kind: "command", run: newProjectDialog },
    { label: "Toggle theme", kind: "command", run: () => $("theme-btn").click() },
    ...(store.overview?.approvals || []).map((a) => ({ label: `${a.id} · ${a.summary}`, kind: "approval", run: () => go(`/approvals/${a.id}`) })),
    ...projects.map((p) => ({ label: `${p.id}${p.key ? ` · ${p.key}` : ""} · ${p.title}`, kind: human(p.state), run: () => go(`/projects/${p.id}`) })),
  ];
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    paletteItems = base.filter((i) => !q || i.label.toLowerCase().includes(q)).slice(0, 40);
    paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
    $("palette-list").replaceChildren(...paletteItems.map((it, i) => h("li", { role: "option", "aria-selected": String(i === paletteIndex),
      onclick: () => { dlg.close(); it.run(); } }, h("span", { text: it.label }), h("span", { class: "kind", text: it.kind }))));
  };
  input.value = ""; paletteIndex = 0; draw();
  input.oninput = () => { paletteIndex = 0; draw(); };
  input.onkeydown = (ev) => {
    if (ev.key === "ArrowDown") { paletteIndex = Math.min(paletteIndex + 1, paletteItems.length - 1); draw(); ev.preventDefault(); }
    else if (ev.key === "ArrowUp") { paletteIndex = Math.max(paletteIndex - 1, 0); draw(); ev.preventDefault(); }
    else if (ev.key === "Enter" && paletteItems[paletteIndex]) { dlg.close(); paletteItems[paletteIndex].run(); }
  };
  dlg.showModal(); input.focus();
}
$("palette-btn").addEventListener("click", openPalette);

// ------------------------------------------------------------------ keyboard
let gPending = false;
document.addEventListener("keydown", (ev) => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") { ev.preventDefault(); openPalette(); return; }
  if (ev.key === "Escape" && !$("drawer").hidden) { closeDrawer(); return; }
  if (typing) return;
  if (ev.key === "/") { const s = $("project-search"); if (s) { ev.preventDefault(); s.focus(); } else { ev.preventDefault(); go("/projects"); } return; }
  if (gPending) {
    gPending = false;
    const map = { o: "/overview", p: "/projects", a: "/approvals", g: "/agents", e: "/activity", k: "/knowledge", r: "/programmes" };
    if (map[ev.key]) { go(map[ev.key]); ev.preventDefault(); }
    return;
  }
  if (ev.key === "g") { gPending = true; setTimeout(() => (gPending = false), 900); }
  if (ev.key === "n") newProjectDialog();
});

// ------------------------------------------------------------------ live updates (SSE)
let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    // Do not re-render under someone typing a note or filling a form.
    const active = document.activeElement;
    if ($("modal").open || $("palette").open || (active && ["TEXTAREA"].includes(active.tagName))) { scheduleRefresh(); return; }
    store.projects = null;
    META = { ...META, version: null };
    render();
  }, 500);
}
function connect() {
  const es = new EventSource("/api/stream");
  const set = (cls, text) => { $("live-dot").className = `dot ${cls}`; $("live-text").textContent = text; };
  es.addEventListener("open", () => set("ok pulse", "Live"));
  es.addEventListener("change", scheduleRefresh);
  es.addEventListener("error", () => set("warn", "Reconnecting…"));
}

// ------------------------------------------------------------------ boot
applyTheme();
window.addEventListener("hashchange", () => { closeDrawer(); render(); $("main").focus({ preventScroll: true }); });
render();
connect();
loadMeta().catch(() => {}).finally(() => setInterval(() => document.querySelectorAll("time.when").forEach((t) => (t.textContent = ago(t.getAttribute("datetime")))),
  1000 * (META.ui.refresh_fallback_s || 30)));
