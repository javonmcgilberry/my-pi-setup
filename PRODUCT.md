# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is a solo developer and Pi power user who relies on a deeply customized coding-agent environment for complex coding, research, diagnosis, and extension development. A secondary audience is Pi users and extension authors who may adopt the components deliberately released as open-source packages.

## Product Purpose

This workspace is a personal Pi workbench and extension incubator. It assembles agents, skills, diagnostics, browser tooling, orchestration, and operational visibility into one environment that helps its owner complete demanding software work with more control and less manual coordination. The root product record is intentionally shared authority: anything built within this workspace should inherit the same durable product principles unless a scoped product record explicitly refines them. Success means the workspace remains dependable for daily use while selected extensions can mature into understandable, reusable packages for the wider Pi ecosystem.

## Positioning

Unlike a generic Pi installation or a loose extension collection, this workspace combines a power user's real operating configuration with the development and validation environment for extensions born from that workflow. Its differentiator is the tight feedback loop between daily use, instrumentation, safety constraints, and package-quality extraction—not a claim that every private configuration artifact is itself a distributable product.

## Operating Context

- Used primarily inside Pi's terminal/TUI coding-agent runtime.
- Supports coding, repository analysis, research, browser-assisted work, multi-agent orchestration, diagnostics, and extension development.
- Includes a localhost browser surface for session spend and activity visibility.
- Uses Pi session logs, extension lifecycle hooks, local configuration, and subagent artifacts as operational inputs.
- The workspace is both a live personal environment and an incubation area; reusable packages must be separated from machine-specific state and private configuration before release.

## Capabilities and Constraints

- Provides custom and third-party Pi extensions, agent definitions, skills, MCP integrations, browser automation, subagent coordination, and code diagnostics.
- The session spend dashboard's localhost HTTP surface is read-only and derives totals from provider-reported session-log costs without estimating missing prices. The separate explicit maintenance script may delete chat trees only when all Pi sessions are closed and after committing content-free usage and tool-count metrics to the local retention ledger.
- `pi-prewalk` and the session spend dashboard are intended candidates for open-source release; the exact package boundaries, names, licensing, support policy, and release timeline remain undecided.
- This repository is the canonical portable Pi setup, while Pi core and separately owned packages retain their own repositories. `PRODUCT.md` remains at this root by design so its principles govern terminal/TUI behavior, tracked skills and extensions, localhost web surfaces, and future setup work. Scoped records may add product-specific facts but should not silently contradict this shared authority.
- Future work must not expose credentials, private session content, machine-specific paths, or other local state in distributable packages.
- Compatibility with Pi and interactions among concurrently loaded extensions are material constraints; extension ordering, tool ownership, context hooks, provider overlays, reload behavior, and lifecycle cleanup require explicit validation.

## Brand Commitments

- Preserve established Pi ecosystem terminology and native command conventions where extensions integrate with Pi.
- `pi-prewalk` and “Session Spend Dashboard” are the current working product names for the two explicitly identified open-source candidates; naming may be revisited before publication.
- The workspace should read as an expert power-user toolset rather than implying an official Pi distribution.

## Evidence on Hand

- `package.json` records the portable Pi extension/tooling environment.
- `AGENTS.md` records source ownership, orchestration, context-management, and worktree safety rules.
- `extensions/session-spend-dashboard/` contains a working read-only dashboard implementation and tests.
- `extensions/session-spend-dashboard/README.md` documents the dashboard's commands, data model, routes, refresh behavior, and security guarantees.
- `docs/research/2026-08-05-pi-session-spend-dashboard.md` records comparative research and the rationale for a focused read-only dashboard.
- `docs/research/2026-08-04-pi-tool-output-ui-options.md` records current Pi and Code Mode output-presentation constraints.
- `settings.json` references the pinned `prewalk` submodule; that submodule retains its own history and release boundary.
- No confirmed testimonials, adoption metrics, pricing, release guarantees, or public-package claims are on hand; future work must not fabricate them.

## Product Principles

1. **Prove it in real use.** Let daily power-user workflows expose integration problems before extracting a public package.
2. **Keep control visible.** Make model behavior, agent activity, spend, and lifecycle state inspectable without turning observability into hidden automation.
3. **Compose safely.** Treat extension ordering, shared tools, context mutation, provider ownership, and cleanup as product-level reliability concerns.
4. **Separate personal state from public product.** Preserve the freedom of a bespoke local setup while giving open-source packages explicit boundaries, documentation, tests, and privacy guarantees.
5. **Prefer truthful evidence.** Report recorded data and validated behavior; do not invent costs, compatibility, adoption, or product claims.
