# Session Spend Dashboard

A read-only localhost dashboard for Pi session spend and activity. It reads the session
logs Pi already writes and serves a live view of them. It cannot change anything.

## Use it

From inside any Pi session:

```text
/spend-dashboard start     launch on http://127.0.0.1:4310
/spend-dashboard open      launch if needed, then open a browser
/spend-dashboard status    show port, watch mode, connected browsers, session count
/spend-dashboard restart
/spend-dashboard stop
```

Pass a port to override the default: `/spend-dashboard start 4400`.

The extension is auto-discovered from `~/.pi/agent/extensions/`. Run `/reload` after
editing it. The server starts only when you ask for it and shuts down with the session.

## What it shows

Total spend, token breakdown, model calls, sessions, projects, and live subagent runs;
daily spend over time; per-model and per-project tables; and a session table with
activity, project, model, tokens, cost, and last-updated time. Filter and sort are
client-side.

Session activity is reported as:

| Badge | Meaning |
| --- | --- |
| `live` | a Pi Subagents run artifact reports this session's run as `running` |
| `active` | written within the last 5 minutes |
| `idle` | written within the last 24 hours |
| `dormant` | older than that |

Pi does not record that a session ended, so no state claims one did.

## How the numbers are produced

Costs are the values each provider recorded in the session log. Nothing is estimated,
and no price table is bundled. A call whose log has no cost contributes `0` and is
counted in "without a reported price".

Two details matter for the totals:

- **Forked and resumed sessions replay their ancestor's entries**, so the same call sits
  in several files. Each call is counted once and attributed to the earliest session
  containing it. That session's row shows the spend; later ones show it as `inherited`.
  Summing the files naively roughly doubles the real total.
- **`toolResult` usage from the `subagent` tool restates work that is also stored as its
  own nested session file**, so it is skipped where it appears and counted from the
  subagent's own session instead.

Because of the first rule, the totals, per-project, per-model, per-provider, and
per-day breakdowns all sum to the same figure.

Assistant messages plus `compaction` and `branch_summary` entries carry usage, and all
three are included.

## Read-only guarantees

- Binds to `127.0.0.1` only, so it is not reachable from the network.
- `GET` and `HEAD` only; every other method returns `405` with `Allow: GET, HEAD`.
- Requests whose `Host` is not localhost are refused with `421`, which blocks
  DNS-rebinding from a page in your browser.
- No CORS headers, so other origins cannot read the data.
- A restrictive `Content-Security-Policy`, and no external fonts, scripts, or styles.
- Session files are only ever read.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | dashboard |
| `/app.css`, `/app.js` | static assets |
| `/api/snapshot` | current aggregate as JSON |
| `/api/stream` | Server-Sent Events, pushed when session files change |
| `/api/health` | server state, no session content |

## Refresh behaviour

A recursive watch on the sessions directory triggers a rescan, debounced by 750&nbsp;ms,
with a 30&nbsp;second safety rescan in case the watch misses an event or is unavailable.
Parsed files are cached by size and mtime, so a rescan only re-reads what changed, and
scans never overlap. The first scan of a large history takes a few seconds; the UI shows
a loading state until it lands.

## Tests

```sh
cd ~/.pi/agent/extensions/session-spend-dashboard
node --test test/*.test.ts
```

No dependencies: Node's built-in runner and TypeScript support cover it.
