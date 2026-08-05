# Pi session spend dashboards

## Best matches

| Project | Browser UI | Updates | Pi data | Useful views | Main limitation |
|---|---|---|---|---|---|
| [Pi Usage Dashboard](https://github.com/mralifakbar/pi-usage-dashboard) | `localhost:33123` | Live SSE; JSONL file watcher with 1-second debounce | `~/.pi/agent/sessions/` plus custom sources | Token and cost totals, daily/weekly/monthly charts, model breakdown, projects, sessions | Includes session actions and extension/config management; no documented read-only mode |
| [pi-cost](https://github.com/NikiforovAll/pi-cost) | `localhost:5461` | Manual refresh; 30-second server cache | `~/.pi/agent/sessions/` | Overview, project, session, per-message actual or estimated cost | No file watcher, SSE, subagent attribution, or live status |
| [Agent Cost Dashboard](https://github.com/mrexodia/agent-cost-dashboard) | `localhost:8753` | Rebuilds data when the page loads | Pi, Oh My Pi, Claude Code, Codex, Gemini | Daily spend, model and tool tables, projects, sessions, grouped subagents | No live stream or machine-readable API |
| [Pi Agent Dashboard](https://github.com/BlackBeltTechnology/pi-agent-dashboard) | `localhost:8000` | Live WebSockets | Extension events plus Pi session files | Active sessions, messages, tools, tokens, costs, model, thinking level | Full session-control product; aggregate spend analytics are limited |
| [CodeBurn](https://github.com/paperwave/codeburn) | No; terminal TUI | Refreshing terminal view | Native Pi provider | Cost by model, project, tool, and activity; JSON/CSV reports | No localhost web UI |
| [pi-token-cost-ledger](https://github.com/EstebanForge/pi-token-cost-ledger) | No; Pi command | Records assistant messages | Extension event stream and daily JSONL ledger | Daily and session token/cost summaries | Ledger and command output only |
| [pi-otel-telemetry](https://github.com/mprokopov/pi-otel-telemetry) | No bundled UI | Streaming OpenTelemetry | Pi extension events | Sessions, model calls, tools, tokens, cost, latency | Requires an OTel backend and separate dashboard |

## Closest fit

[Pi Usage Dashboard](https://github.com/mralifakbar/pi-usage-dashboard) already implements the requested data path and update model:

- watches Pi session JSONL files with Chokidar;
- pushes updates through `/api/usage/stream` using Server-Sent Events;
- aggregates tokens and costs by time, model, project, and session;
- runs locally without sending session data to a hosted service;
- supports provider-reported cost and configurable per-model pricing.

Its extra controls conflict with a visual-only scope. The documented API includes terminal launch, session actions, pricing writes, source writes, and extension deletion. A focused dashboard should keep the parser, aggregation model, and SSE approach while exposing read-only routes and views.

## Lightweight alternative

`pi-cost` is installable as a Pi extension:

```sh
pi install npm:pi-cost
```

Run `/cost start`, then `/cost open`. It is the quickest safe evaluation because its documented UI centers on spend exploration rather than session control. Data refresh is explicit rather than live.

## Recommended build direction

Build a small read-only Pi extension around the session files already stored in `~/.pi/agent/sessions/`:

1. Parse assistant-message `usage` records and preserve provider-reported cost.
2. Watch session files and broadcast debounced SSE updates.
3. Show summary totals, active/recent sessions, project grouping, model breakdown, and a time chart.
4. Keep every server route `GET`-only.
5. Omit thresholds, alerts, session control, terminals, configuration editors, and extension management.

Pi Subagents also writes stable lifecycle data to each async run's `status.json` and `events.jsonl`, including state, steps, results, tokens, cost, model, tool count, and nested children. Those files can supply live run status without inferring it from session-file timestamps.

## Sources

- [Pi Usage Dashboard README](https://github.com/mralifakbar/pi-usage-dashboard)
- [pi-cost user guide](https://nikiforovall.github.io/pi-cost/user-guide)
- [Agent Cost Dashboard README](https://github.com/mrexodia/agent-cost-dashboard)
- [Pi Agent Dashboard README](https://github.com/BlackBeltTechnology/pi-agent-dashboard)
- [CodeBurn README](https://github.com/paperwave/codeburn)
- [pi-token-cost-ledger README](https://github.com/EstebanForge/pi-token-cost-ledger)
- [pi-otel-telemetry README](https://github.com/mprokopov/pi-otel-telemetry)
- [Pi Subagents lifecycle artifacts](https://github.com/mariozechner/pi-coding-agent)
