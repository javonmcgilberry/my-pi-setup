export const INDEX_HTML = `<!doctype html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Pi Session Spend</title>
<link rel="stylesheet" href="/app.css">
</head>
<body>
<a class="skip" href="#totals">Skip to totals</a>
<header class="topbar">
  <div class="brand">
    <h1>Pi Session Spend</h1>
    <p id="root-path" class="muted">Reading sessions&hellip;</p>
  </div>
  <div class="topbar-right">
    <p class="stream" aria-live="polite">
      <span id="stream-dot" class="dot" data-state="connecting" aria-hidden="true"></span>
      <span id="stream-label">Connecting</span>
    </p>
    <button id="theme-toggle" type="button" aria-label="Theme: Auto. Switch to light theme">Theme: Auto</button>
  </div>
</header>

<main>
  <p id="banner" class="banner" role="status" hidden></p>

  <section aria-labelledby="totals-heading">
    <h2 id="totals-heading" class="sr-only">Totals</h2>
    <ul id="totals" class="cards">
      <li class="card"><span class="card-label">Total spend</span><strong id="stat-cost" class="card-value">&mdash;</strong><span id="stat-cost-note" class="card-note">&nbsp;</span></li>
      <li class="card"><span class="card-label">Tokens</span><strong id="stat-tokens" class="card-value">&mdash;</strong><span id="stat-tokens-note" class="card-note">&nbsp;</span></li>
      <li class="card"><span class="card-label">Model calls</span><strong id="stat-calls" class="card-value">&mdash;</strong><span id="stat-calls-note" class="card-note">&nbsp;</span></li>
      <li class="card"><span class="card-label">Sessions</span><strong id="stat-sessions" class="card-value">&mdash;</strong><span id="stat-sessions-note" class="card-note">&nbsp;</span></li>
      <li class="card"><span class="card-label">Projects</span><strong id="stat-projects" class="card-value">&mdash;</strong><span id="stat-projects-note" class="card-note">&nbsp;</span></li>
      <li class="card"><span class="card-label">Live runs</span><strong id="stat-runs" class="card-value">&mdash;</strong><span id="stat-runs-note" class="card-note">&nbsp;</span></li>
    </ul>
  </section>

  <section class="panel" aria-labelledby="chart-heading">
    <div class="panel-head">
      <h2 id="chart-heading">Spend over time</h2>
      <span id="chart-range" class="muted"></span>
    </div>
    <div id="chart" class="chart" role="img" aria-label="Daily spend chart"></div>
    <table class="sr-only">
      <caption>Daily spend data</caption>
      <thead><tr><th scope="col">Date</th><th scope="col">Spend</th><th scope="col">Tokens</th><th scope="col">Calls</th></tr></thead>
      <tbody id="chart-data-body"></tbody>
    </table>
    <p id="chart-empty" class="empty" hidden>No dated spend yet.</p>
  </section>

  <div class="split">
    <section class="panel" aria-labelledby="models-heading">
      <div class="panel-head"><h2 id="models-heading">Models</h2></div>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Spend by model table">
        <table class="grid">
          <caption class="sr-only">Spend by model</caption>
          <thead><tr><th scope="col">Model</th><th scope="col">Provider</th><th scope="col" class="num">Tokens</th><th scope="col" class="num">Cost</th></tr></thead>
          <tbody id="models-body"></tbody>
        </table>
      </div>
      <p id="models-empty" class="empty" hidden>No model usage yet.</p>
    </section>

    <section class="panel" aria-labelledby="projects-heading">
      <div class="panel-head"><h2 id="projects-heading">Projects</h2></div>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Spend by project table">
        <table class="grid">
          <caption class="sr-only">Spend by project</caption>
          <thead><tr><th scope="col">Project</th><th scope="col" class="num">Sessions</th><th scope="col" class="num">Tokens</th><th scope="col" class="num">Cost</th></tr></thead>
          <tbody id="projects-body"></tbody>
        </table>
      </div>
      <p id="projects-empty" class="empty" hidden>No projects yet.</p>
    </section>
  </div>

  <section class="panel" aria-labelledby="sessions-heading">
    <div class="panel-head">
      <h2 id="sessions-heading">Sessions</h2>
      <div class="controls">
        <label for="filter" class="sr-only">Filter sessions</label>
        <input id="filter" type="search" placeholder="Filter by project, model, or id" autocomplete="off">
        <label for="sort" class="sr-only">Sort sessions</label>
        <select id="sort">
          <option value="activity">Activity</option>
          <option value="cost">Cost</option>
          <option value="tokens">Tokens</option>
          <option value="updated">Last updated</option>
        </select>
      </div>
    </div>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Session activity and spend table">
      <table class="grid sessions">
        <caption class="sr-only">Session activity and spend</caption>
        <thead><tr>
          <th scope="col">Status</th><th scope="col">Session</th><th scope="col">Project</th>
          <th scope="col">Model</th><th scope="col" class="num">Tokens</th>
          <th scope="col" class="num">Cost</th><th scope="col" class="num">Updated</th>
        </tr></thead>
        <tbody id="sessions-body"></tbody>
      </table>
    </div>
    <p id="sessions-empty" class="empty" hidden>No sessions match.</p>
    <p id="sessions-count" class="muted"></p>
    <div class="more-row"><button id="sessions-more" type="button" hidden>Load more sessions</button></div>
  </section>

  <footer class="footnote">
    <p>Costs are the values each provider reported in the session log; nothing is estimated. Spend replayed into a forked or resumed session stays attributed to the session that first paid for it, so every breakdown adds up to the same total.</p>
  </footer>
</main>
<script src="/app.js"></script>
</body>
</html>
`;

export const APP_CSS = `:root {
  color-scheme: light dark;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --border: #dfe3e8;
  --text: #1b1f24;
  --muted: #5c6672;
  --accent: #2f6feb;
  --bar: #2f6feb;
  --bar-soft: #d6e2fb;
  --live: #1a7f45;
  --active: #2f6feb;
  --idle: #8a6d1f;
  --dormant: #68727d;
  --shadow: 0 1px 2px rgba(16, 22, 32, .06);
}
[data-theme="dark"] {
  --bg: #0f1216;
  --panel: #161b22;
  --border: #262d36;
  --text: #e6edf3;
  --muted: #93a1b1;
  --accent: #6ea8ff;
  --bar: #6ea8ff;
  --bar-soft: #23324a;
  --live: #48d17d;
  --active: #6ea8ff;
  --idle: #d8b34a;
  --dormant: #7d8792;
  --shadow: none;
}
@media (prefers-color-scheme: dark) {
  [data-theme="auto"] {
    --bg: #0f1216; --panel: #161b22; --border: #262d36; --text: #e6edf3;
    --muted: #93a1b1; --accent: #6ea8ff; --bar: #6ea8ff; --bar-soft: #23324a;
    --live: #48d17d; --active: #6ea8ff; --idle: #d8b34a; --dormant: #7d8792; --shadow: none;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.skip {
  position: absolute; left: -999px; top: 0; z-index: 10;
  background: var(--panel); color: var(--text); padding: .6rem 1rem; border-radius: 0 0 6px 0;
}
.skip:focus { left: 0; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
.topbar {
  display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; justify-content: space-between;
  padding: 1rem 1.25rem; border-bottom: 1px solid var(--border); background: var(--panel);
}
.topbar h1 { margin: 0; font-size: 1.05rem; letter-spacing: .2px; }
.brand p { margin: .15rem 0 0; font-size: .8rem; word-break: break-all; }
.topbar-right { display: flex; align-items: center; gap: .9rem; }
.muted { color: var(--muted); }
.stream { display: flex; align-items: center; gap: .45rem; margin: 0; font-size: .82rem; color: var(--muted); }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--dormant); flex: none; }
.dot[data-state="live"] { background: var(--live); }
.dot[data-state="connecting"] { background: var(--idle); }
.dot[data-state="lost"] { background: #d9534f; }
button, input, select {
  font: inherit; color: var(--text); background: var(--panel);
  border: 1px solid var(--border); border-radius: 6px; padding: .35rem .6rem; min-height: 44px;
}
button { cursor: pointer; }
button:hover { border-color: var(--accent); }
main { padding: 1.25rem; max-width: 1400px; margin: 0 auto; display: grid; gap: 1.25rem; }
.banner {
  margin: 0; padding: .7rem .9rem; border: 1px solid var(--border);
  border-left: 3px solid var(--idle); border-radius: 6px; background: var(--panel);
}
.cards { list-style: none; margin: 0; padding: 0; display: grid; gap: .9rem; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); }
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
  padding: .85rem .95rem; box-shadow: var(--shadow); display: grid; gap: .15rem;
}
.card-label { font-size: .74rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.card-value { font-size: 1.5rem; font-variant-numeric: tabular-nums; line-height: 1.2; }
.card-note { font-size: .76rem; color: var(--muted); }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); overflow: hidden; }
.panel-head {
  display: flex; flex-wrap: wrap; gap: .75rem; align-items: center; justify-content: space-between;
  padding: .8rem 1rem; border-bottom: 1px solid var(--border);
}
.panel-head h2 { margin: 0; font-size: .95rem; }
.controls { display: flex; gap: .5rem; flex-wrap: wrap; }
.controls input { min-width: min(260px, 60vw); }
.split { display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.chart { display: flex; align-items: flex-end; gap: 2px; height: 168px; padding: 1rem; overflow-x: auto; }
.chart-col { flex: 1 0 8px; min-width: 8px; display: flex; flex-direction: column; justify-content: flex-end; height: 100%; }
.chart-bar {
  background: var(--bar); border-radius: 2px 2px 0 0; height: 100%;
  transform: scaleY(var(--bar-scale, .02)); transform-origin: bottom; transition: transform .2s ease;
}
.chart-col:hover .chart-bar { background: var(--accent); filter: brightness(1.15); }
.table-scroll { max-width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; }
.table-scroll:focus-visible { outline-offset: -3px; }
table.grid { width: 100%; border-collapse: collapse; }
.grid th, .grid td { padding: .5rem .7rem; text-align: left; border-bottom: 1px solid var(--border); }
.grid thead th { font-size: .74rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 600; }
.grid tbody tr:last-child td { border-bottom: 0; }
.grid tbody tr:hover { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.wrapcell { max-width: 320px; overflow-wrap: anywhere; }
.bar-cell { position: relative; }
.bar-fill { position: absolute; inset: 0 auto 0 0; background: var(--bar-soft); border-radius: 3px; z-index: 0; }
.bar-text { position: relative; z-index: 1; }
.badge {
  display: inline-block; font-size: .7rem; text-transform: uppercase; letter-spacing: .05em;
  padding: .16rem .45rem; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap;
}
.badge[data-activity="live"] { color: var(--live); }
.badge[data-activity="active"] { color: var(--active); }
.badge[data-activity="idle"] { color: var(--idle); }
.badge[data-activity="dormant"] { color: var(--dormant); }
.sub { font-size: .74rem; color: var(--muted); }
.empty { margin: 0; padding: 1.25rem 1rem; color: var(--muted); text-align: center; }
#sessions-count { padding: .6rem 1rem; margin: 0; font-size: .78rem; border-top: 1px solid var(--border); }
.more-row { display: flex; justify-content: center; padding: 0 1rem 1rem; }
.more-row:has(button[hidden]) { display: none; }
.footnote { color: var(--muted); font-size: .78rem; }
.footnote p { margin: 0; }
.skeleton { color: var(--muted); }
@media (max-width: 720px) {
  .sessions thead th:nth-child(4), .sessions tbody td:nth-child(4) { display: none; }
  .card-value { font-size: 1.25rem; }
}
@media (prefers-reduced-motion: reduce) { .chart-bar { transition: none; } }
`;

export const APP_JS = `(() => {
  "use strict";

  const el = (id) => document.getElementById(id);
  const nodes = {
    root: el("root-path"), dot: el("stream-dot"), streamLabel: el("stream-label"),
    banner: el("banner"), theme: el("theme-toggle"),
    cost: el("stat-cost"), costNote: el("stat-cost-note"),
    tokens: el("stat-tokens"), tokensNote: el("stat-tokens-note"),
    calls: el("stat-calls"), callsNote: el("stat-calls-note"),
    sessions: el("stat-sessions"), sessionsNote: el("stat-sessions-note"),
    projects: el("stat-projects"), projectsNote: el("stat-projects-note"),
    runs: el("stat-runs"), runsNote: el("stat-runs-note"),
    chart: el("chart"), chartDataBody: el("chart-data-body"), chartEmpty: el("chart-empty"), chartRange: el("chart-range"),
    modelsBody: el("models-body"), modelsEmpty: el("models-empty"),
    projectsBody: el("projects-body"), projectsEmpty: el("projects-empty"),
    sessionsBody: el("sessions-body"), sessionsEmpty: el("sessions-empty"), sessionsCount: el("sessions-count"),
    filter: el("filter"), sort: el("sort"), sessionsMore: el("sessions-more"),
  };

  let snapshot = null;
  const SESSION_PAGE_SIZE = 200;
  let visibleSessionLimit = SESSION_PAGE_SIZE;

  const money = (n) => {
    const value = Number(n) || 0;
    if (value > 0 && value < 0.01) return "<$0.01";
    return "$" + value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const count = (n) => (Number(n) || 0).toLocaleString();
  const compact = (n) => {
    const value = Number(n) || 0;
    if (value < 1000) return String(Math.round(value));
    if (value < 1e6) return (value / 1e3).toFixed(value < 1e4 ? 1 : 0) + "k";
    if (value < 1e9) return (value / 1e6).toFixed(value < 1e7 ? 1 : 0) + "M";
    return (value / 1e9).toFixed(2) + "B";
  };
  const ago = (ts) => {
    const value = Number(ts) || 0;
    if (!value) return "unknown";
    const diff = Date.now() - value;
    if (diff < 0) return "just now";
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + "h ago";
    const days = Math.floor(hours / 24);
    if (days < 30) return days + "d ago";
    return new Date(value).toLocaleDateString();
  };

  const cell = (text, className) => {
    const td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text;
    return td;
  };

  function barCell(text, ratio) {
    const td = document.createElement("td");
    td.className = "num bar-cell";
    const fill = document.createElement("span");
    fill.className = "bar-fill";
    fill.style.width = Math.max(0, Math.min(1, ratio)) * 100 + "%";
    const label = document.createElement("span");
    label.className = "bar-text";
    label.textContent = text;
    td.append(fill, label);
    return td;
  }

  const THEME_ORDER = ["auto", "light", "dark"];

  function updateThemeControl(mode) {
    const currentIndex = THEME_ORDER.indexOf(mode);
    const safeMode = currentIndex >= 0 ? mode : "auto";
    const nextMode = THEME_ORDER[(THEME_ORDER.indexOf(safeMode) + 1) % THEME_ORDER.length];
    const currentLabel = safeMode[0].toUpperCase() + safeMode.slice(1);
    nodes.theme.textContent = "Theme: " + currentLabel;
    nodes.theme.setAttribute("aria-label", "Theme: " + currentLabel + ". Switch to " + nextMode + " theme");
  }

  function setTheme(mode) {
    document.documentElement.dataset.theme = mode;
    updateThemeControl(mode);
    // Storage throws when the browser blocks it; the theme still applies for this visit.
    try { localStorage.setItem("spend-theme", mode); } catch { /* not persisted */ }
  }

  nodes.theme.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "auto";
    const currentIndex = THEME_ORDER.indexOf(current);
    setTheme(THEME_ORDER[((currentIndex >= 0 ? currentIndex : 0) + 1) % THEME_ORDER.length]);
  });

  try {
    const saved = localStorage.getItem("spend-theme");
    setTheme(THEME_ORDER.includes(saved) ? saved : "auto");
  } catch { /* keep the default theme */ }
  updateThemeControl(document.documentElement.dataset.theme || "auto");

  function stream(state, label) {
    nodes.dot.dataset.state = state;
    nodes.streamLabel.textContent = label;
  }

  function banner(message) {
    if (!message) {
      nodes.banner.hidden = true;
      nodes.banner.textContent = "";
      return;
    }
    nodes.banner.hidden = false;
    nodes.banner.textContent = message;
  }

  function renderChart(days) {
    nodes.chart.textContent = "";
    nodes.chartDataBody.textContent = "";
    if (!days.length) {
      nodes.chartEmpty.hidden = false;
      nodes.chartRange.textContent = "";
      return;
    }
    nodes.chartEmpty.hidden = true;
    const peak = days.reduce((max, d) => Math.max(max, d.cost), 0) || 1;
    nodes.chartRange.textContent = days[0].day + " to " + days[days.length - 1].day;
    nodes.chart.setAttribute("aria-label",
      "Daily spend from " + days[0].day + " to " + days[days.length - 1].day + ", peak " + money(peak));
    for (const day of days) {
      const dataRow = document.createElement("tr");
      dataRow.append(cell(day.day));
      dataRow.append(cell(money(day.cost), "num"));
      dataRow.append(cell(count(day.totalTokens), "num"));
      dataRow.append(cell(count(day.calls), "num"));
      nodes.chartDataBody.append(dataRow);

      const col = document.createElement("div");
      col.className = "chart-col";
      col.title = day.day + " — " + money(day.cost) + " · " + compact(day.totalTokens) + " tokens · " + count(day.calls) + " calls";
      const bar = document.createElement("div");
      bar.className = "chart-bar";
      bar.style.setProperty("--bar-scale", String(Math.max(.02, day.cost / peak)));
      col.append(bar);
      nodes.chart.append(col);
    }
  }

  function renderModels(models) {
    nodes.modelsBody.textContent = "";
    nodes.modelsEmpty.hidden = models.length > 0;
    const peak = models.reduce((max, m) => Math.max(max, m.cost), 0) || 1;
    for (const model of models) {
      const tr = document.createElement("tr");
      tr.append(cell(model.model, "wrapcell"));
      tr.append(cell(model.providers.join(", ") || "unknown", "sub"));
      tr.append(cell(compact(model.totalTokens), "num"));
      tr.append(barCell(money(model.cost), model.cost / peak));
      nodes.modelsBody.append(tr);
    }
  }

  function renderProjects(projects) {
    nodes.projectsBody.textContent = "";
    nodes.projectsEmpty.hidden = projects.length > 0;
    const peak = projects.reduce((max, p) => Math.max(max, p.cost), 0) || 1;
    for (const project of projects) {
      const tr = document.createElement("tr");
      const name = cell(project.label, "wrapcell");
      name.title = project.cwd;
      tr.append(name);
      tr.append(cell(count(project.sessions), "num"));
      tr.append(cell(compact(project.totalTokens), "num"));
      tr.append(barCell(money(project.cost), project.cost / peak));
      nodes.projectsBody.append(tr);
    }
  }

  const RANK = { live: 0, active: 1, idle: 2, dormant: 3 };

  function renderSessions(sessions) {
    const term = nodes.filter.value.trim().toLowerCase();
    const mode = nodes.sort.value;
    let rows = sessions;
    if (term) {
      rows = rows.filter((s) =>
        (s.label + " " + s.cwd + " " + s.sessionId + " " + (s.name || "") + " " + s.models.join(" ") + " " + s.providers.join(" "))
          .toLowerCase().includes(term));
    }
    rows = rows.slice().sort((a, b) => {
      if (mode === "cost") return b.cost - a.cost;
      if (mode === "tokens") return b.totalTokens - a.totalTokens;
      if (mode === "updated") return b.updatedAt - a.updatedAt;
      return RANK[a.activity] - RANK[b.activity] || b.updatedAt - a.updatedAt;
    });

    nodes.sessionsBody.textContent = "";
    nodes.sessionsEmpty.hidden = rows.length > 0;
    const visibleRows = rows.slice(0, visibleSessionLimit);
    for (const session of visibleRows) {
      const tr = document.createElement("tr");

      const status = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.dataset.activity = session.activity;
      badge.textContent = session.activity;
      status.append(badge);
      if (session.runState) {
        const runNote = document.createElement("div");
        runNote.className = "sub";
        runNote.textContent = session.runAgent
          ? session.runAgent + " · " + session.runState
          : session.runState;
        status.append(runNote);
      }
      tr.append(status);

      const idCell = document.createElement("td");
      idCell.className = "wrapcell";
      const idText = document.createElement("div");
      idText.textContent = session.name || session.sessionId;
      idCell.append(idText);
      const meta = document.createElement("div");
      meta.className = "sub";
      const bits = [];
      if (session.isSubagent) bits.push("subagent");
      if (session.calls) bits.push(count(session.calls) + " calls");
      if (session.inheritedCost > 0) bits.push(money(session.inheritedCost) + " inherited");
      meta.textContent = bits.join(" · ");
      idCell.append(meta);
      idCell.title = session.relPath;
      tr.append(idCell);

      const project = cell(session.label, "wrapcell");
      project.title = session.cwd;
      tr.append(project);

      tr.append(cell(session.models.join(", ") || "—", "sub wrapcell"));
      tr.append(cell(compact(session.totalTokens), "num"));
      tr.append(cell(money(session.cost), "num"));
      tr.append(cell(ago(session.updatedAt), "num sub"));
      nodes.sessionsBody.append(tr);
    }

    const shown = visibleRows.length;
    nodes.sessionsMore.hidden = shown >= rows.length;
    nodes.sessionsCount.textContent = term
      ? "Showing " + count(shown) + " of " + count(rows.length) + " matching sessions · " + count(sessions.length) + " total"
      : "Showing " + count(shown) + " of " + count(sessions.length) + " sessions";
  }

  function render() {
    if (!snapshot) return;
    const t = snapshot.totals;
    nodes.root.textContent = snapshot.sessionsRoot;
    nodes.cost.textContent = money(t.cost);
    nodes.costNote.textContent = count(t.calls) + " reported calls";
    nodes.tokens.textContent = compact(t.totalTokens);
    nodes.tokensNote.textContent =
      compact(t.input) + " in · " + compact(t.output) + " out · " + compact(t.cacheRead) + " cache read";
    nodes.calls.textContent = count(t.calls);
    nodes.callsNote.textContent = t.callsWithoutReportedCost
      ? count(t.callsWithoutReportedCost) + " without a reported price"
      : "all with a reported price";
    nodes.sessions.textContent = count(t.sessions);
    nodes.sessionsNote.textContent = count(snapshot.sessions.filter((s) => s.isSubagent).length) + " subagent sessions";
    nodes.projects.textContent = count(t.projects);
    nodes.projectsNote.textContent = snapshot.byProvider.length + " providers";
    nodes.runs.textContent = snapshot.runs.available ? count(snapshot.runs.activeRuns) : "n/a";
    nodes.runsNote.textContent = snapshot.runs.available ? "from subagent run artifacts" : "no run artifacts found";

    const notes = [];
    if (snapshot.scan.malformedLines) notes.push(count(snapshot.scan.malformedLines) + " unreadable log lines skipped");
    if (snapshot.scan.truncatedFiles) notes.push(count(snapshot.scan.truncatedFiles) + " oversized session files read partially");
    banner(notes.join(" · "));

    renderChart(snapshot.byDay);
    renderModels(snapshot.byModel);
    renderProjects(snapshot.byProject);
    renderSessions(snapshot.sessions);
  }

  function applyPayload(data) {
    if (data && data.pending) {
      stream("connecting", data.error ? "Scan failed" : "Scanning sessions");
      banner(data.error ? "Could not read sessions: " + data.error : "Reading session logs for the first time…");
      return;
    }
    snapshot = data;
    stream("live", "Live · updated " + new Date(data.generatedAt).toLocaleTimeString());
    render();
  }

  nodes.filter.addEventListener("input", () => {
    visibleSessionLimit = SESSION_PAGE_SIZE;
    if (snapshot) renderSessions(snapshot.sessions);
  });
  nodes.sort.addEventListener("change", () => {
    visibleSessionLimit = SESSION_PAGE_SIZE;
    if (snapshot) renderSessions(snapshot.sessions);
  });
  nodes.sessionsMore.addEventListener("click", () => {
    visibleSessionLimit += SESSION_PAGE_SIZE;
    if (snapshot) renderSessions(snapshot.sessions);
  });

  let source = null;
  function connect() {
    source = new EventSource("/api/stream");
    source.addEventListener("open", () => stream("connecting", "Connected"));
    source.addEventListener("snapshot", (event) => {
      try { applyPayload(JSON.parse(event.data)); }
      catch { banner("Received an unreadable update."); }
    });
    source.addEventListener("error", () => {
      stream("lost", "Reconnecting…");
      source.close();
      setTimeout(connect, 3000);
    });
  }

  fetch("/api/snapshot", { headers: { accept: "application/json" } })
    .then((res) => res.json())
    .then(applyPayload)
    .catch(() => banner("Could not load the first snapshot."))
    .finally(connect);
})();
`;
