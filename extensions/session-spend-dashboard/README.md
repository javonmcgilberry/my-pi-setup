# Session Spend Dashboard

A localhost dashboard for Pi session spend and activity, backed by a content-free SQLite
metrics ledger. The HTTP server is read-only. Explicit maintenance commands can import
metrics and remove expired chat trees after confirmation.

## Use it

From inside any Pi session:

```text
/spend-dashboard open      launch if needed, then open a browser
/spend-dashboard start     launch on http://127.0.0.1:4310
/spend-dashboard status    show port, watch mode, connected browsers, session count
/spend-dashboard restart
/spend-dashboard stop
/spend-dashboard maintain   import metrics and preview expired chats
```

Pi's command hint shows `/spend-dashboard open` as you type. After the command,
the autocomplete menu gives a short description for each action.

Pass a port to override the default: `/spend-dashboard start 4400`.

The extension is loaded from this Pi package. Restart Pi after editing it. The server
starts only when you ask for it and shuts down with the session.

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

## Retention and the metrics ledger

The extension imports session metadata, provider-reported usage, and deduplicated tool-call
counts into `~/.pi/agent/session-metrics/metrics.sqlite`. It does not store prompts,
responses, tool names, tool arguments, tool results, or raw session JSON.
Session titles come from current `session_info` entries while a chat is still
present. If a private metadata file exists under
`~/.pi/agent/session-metadata/summaries/`, its title remains available after
chat retention removes the source log. Summaries are never returned by the
dashboard or copied into the metrics database.

Tracked defaults live in `session-spend-dashboard.json`:

```json
{
  "chatRetentionDays": 7,
  "metricsRetentionDays": 365
}
```

Both values accept whole days from 1 through 3650. Metrics retention cannot be shorter
than chat retention. `/spend-dashboard maintain` updates the ledger and reports what a
cleanup would remove. After closing every Pi session, run
`node scripts/session-maintenance.mjs --apply` from the setup repository to perform the
same import and coverage check and then remove eligible trees. Cleanup is manual: opening
the dashboard never deletes chats.

A root session and its nested child-run directory are one retention unit. The extension
removes the unit only when every file in it is older than the chat cutoff. The active
session is always protected. The maintenance lock prevents concurrent cleanup processes,
and the ledger transaction commits before any transcript is deleted. Cleanup also stops
if a session is unreadable, malformed, truncated, omitted by scan limits, or becomes
active during deletion. A lock left by a crashed maintenance process must be removed
manually after confirming no maintenance process is running. Active-session markers also
fail closed: Pi startup is shut down while cleanup owns the gate, and markers left by an
unclean Pi exit must be removed manually only after confirming that process is gone.

Metrics older than the configured metrics window are deleted from the ledger. Prewalk's
planner/executor receipts remain separate because they encode workflow-specific savings
semantics; its Pi session usage still appears in this general ledger.

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
three are included. Tool calls are counted by stable call ID without retaining their
names or payloads.

## HTTP read-only guarantees

- Binds to `127.0.0.1` only, so it is not reachable from the network.
- `GET` and `HEAD` only; every other method returns `405` with `Allow: GET, HEAD`.
- Requests whose `Host` is not localhost are refused with `421`, which blocks
  DNS-rebinding from a page in your browser.
- No CORS headers, so other origins cannot read the data.
- A restrictive `Content-Security-Policy`, and no external fonts, scripts, or styles.
- HTTP requests cannot delete chats. Deletion requires the explicit standalone
  `--apply` maintenance command, which refuses to run while any Pi session is active.

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
Parsed files are cached by size and mtime, ledger writes are idempotent, and scans never
overlap. Historical ledger rows remain visible after their source chats are deleted.
The first scan of a large history can take a few seconds; the UI shows a loading state
until it lands.

## Tests

```sh
cd ~/.pi/agent/extensions/session-spend-dashboard
node --test test/*.test.ts
```

No external runtime dependencies: Node's built-in SQLite, test runner, and TypeScript
support cover it.
