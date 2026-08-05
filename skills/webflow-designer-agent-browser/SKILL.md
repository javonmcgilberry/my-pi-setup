---
name: webflow-designer-agent-browser
description: Use agent-browser and Chrome DevTools Protocol to inspect, debug, and verify authenticated Webflow Designer sessions with compact snapshots, targeted evidence, and a self-compounding automation loop. Trigger for Designer URLs on design.webflow.com, design.wfdev.io, or wfdev.io; authenticated local Designer QA; extension iframes; canvas or visual debugging; agent-browser; CDP attachment; checks that must observe the user's current unsaved or collaborative Designer tab; and repeated browser work that should become a deterministic reusable helper.
---

# Webflow Designer Agent Browser

Use the best available agent-browser transport for token-efficient Designer exploration while preserving the exact browser state under test. Keep `webflow-designer-playwright` available as the deterministic Playwright baseline. Do not claim this skill replaces it until a real Designer scenario proves the required behavior.

## Select the browser transport by capability

Do not branch on a harness name. Select once before opening or claiming a
session, record the selection, and keep it for the whole task:

1. If the harness exposes the native `agent_browser` tool, select `native`.
   This is the preferred Pi path because the extension returns compact,
   structured results without routing CLI output through a shell.
2. Otherwise, if `command -v agent-browser` and `agent-browser --version`
   succeed, select `cli` and invoke the same operations with the CLI.
3. If neither capability exists, stop with `browser_transport_unavailable`.

Do not silently switch transports after a session starts or after an action
fails. Native and CLI sessions have different ownership state; switching can
open a second browser or leave the first session unclosed. The operation names
in this skill (`open`, `connect`, `tab`, `wait`, `snapshot`, `close`) apply to
both transports. Native actions use `agent_browser`; CLI actions use the
`agent-browser` executable.

## Preconditions

1. Select and record `native` or `cli` using the capability rules above. Run the CLI checks only for `cli`.
2. Do not install a browser transport, download a browser, or change Chrome configuration without approval.
3. Obtain the exact Designer URL, including `pageId`, role simulation, and local port. Prefer the URL from the live tab.
4. Check explicit required local services and extension endpoints before diagnosing product behavior.
5. On `profile_unavailable`, fully quit normal Chrome and run `scripts/browser-runtime.py bootstrap --confirm-sensitive-copy` once. The default source is the normal Chrome `Default` profile; pass `--source-profile <directory-name>` explicitly for another profile. Bootstrap excludes `Local State`, cookie databases, saved-login databases, and Web Data. Then run `start --headed` for a one-time Webflow login and `stop` immediately afterward. Never copy a live/locked profile or transfer cookies or credentials.
5. Choose one mode explicitly and record it in the evidence.

## Reusable helpers

- Run `scripts/capability-catalog.py list [--category <name>]` for the compact deferred helper catalog. Read only the selected helper or direct reference; do not load every helper contract up front.
- Run `scripts/browser-runtime.py status` before authenticated attached work. The runtime owns the dedicated profile, Chrome for Testing process, loopback direct-CDP readiness, bounded watchdog, and exclusive consumer lease. `start` is headless by default; use `start --headed` only for login, MFA, or visual debugging. `release` also stops the owned runtime. Use `plan`, `bootstrap`, `start`, `claim`, `release`, or `stop` only for the lifecycle phase each command names.
- Run `scripts/discover-designer-tabs.py` to query an existing CDP endpoint and return only sanitized Designer tab metadata. Use `--ownership-url` and `--current-session` to inspect known agent-browser ownership without claiming or focusing a tab.
- Run `scripts/discover-designer-tabs.py --attachment-config config/attachment.json --transport <native|cli>` from this skill directory before attaching. The tracked config emits the selected transport's explicit `connect <port>` action for canonical `direct_cdp`. Pass a sanitized surface fixture back with `--surface-fixture`, `--expected-title`, and the required actual `--expected-runtime-mode`; headed verification rejects `HeadlessChrome`, headless verification requires it, and both reject all-`about:blank` managed fallbacks.
- Run `scripts/designer-session.py <attached|isolated> --transport <native|cli>` to preflight a bounded bootstrap and emit transport-specific actions plus mandatory cleanup. It never launches a browser itself. Supply each required service through `--tcp-service` or `--http-service`; a failed preflight stops plan emission and identifies the unavailable label without exposing its target.
- Pipe agent-browser JSON or a saved report through `scripts/sanitize-evidence.py` before sharing it. The sanitizer redacts secret-bearing keys, sensitive headers, unsafe query values, long strings, and oversized collections.
- Run `scripts/automation-evidence.py <sanitized-run-shape.json>` only after reconstructing the complete run. It rejects incomplete inventories. Use its private evidence queue only for non-sensitive candidate shapes; reviewed promotion is a separate maintenance pass.
- Run `scripts/guarded-site-authorization.py <sanitized-surface.json> --expected-site-id <site-id>` to identify one exact authorization checkbox across visible pages. The helper validates the selection and callback postconditions only when their explicit flags are present; agent-browser remains responsible for browser actions.
- Run `scripts/verify-workspace-build.py --source <source-module> --built <generated-module>` before published runtime QA when a local provider package imports ignored generated workspace output.
- Run `node scripts/cdp-frame-eval.mjs ... --dry-run` when agent-browser cannot retain context for an out-of-process iframe. It evaluates a file-backed expression in the matching frame without printing target URLs. Use `--visible-replacement-selector <selector>` with a bounded `--observation-ms` to report count-only overlap and blank-gap evidence during one replacement.

These helpers cover deterministic setup and evidence handling only. Use the selected browser transport directly for interaction, diffs, diagnostics, screenshots, traces, and profiles.

## Browser ownership and operating modes

Keep personal browsing and agent automation in separate Chrome profiles:

- **The user's normal Chrome Work profile is user-owned.** The user may open it and browse normally while routine automation runs. Do not attach to it, close its tabs, reuse its profile directory, or terminate its processes during routine work.
- **The copied Webflow profile is agent-owned.** It lives under `~/.config/webflow-designer-agent-browser/chrome-user-data/` and is the only profile used by `browser-runtime.py`. The user should not browse in this profile while automation is running because shared tabs, focus, navigation, and profile locks make tests nondeterministic.
- **All managed Webflow automation uses Chrome for Testing.** Never launch `/Applications/Google Chrome.app` from this skill and never point automation at the user's normal profile directory. If Chrome for Testing is unavailable, stop with `chrome_unavailable` rather than falling back.
- **Headless is the routine default.** Run `scripts/browser-runtime.py start` for invisible, repeatable authenticated automation. The dedicated profile remains separate from the user's normal Chrome profile. The default watchdog limit is 1,800 seconds; use a larger bounded `--max-runtime-seconds` only when the task is expected to need it.
- **Headed is an explicit temporary mode.** Run `scripts/browser-runtime.py start --headed` only for manual login, MFA, user observation, or visual debugging. After that work, close the managed agent-browser session and release the consumer; release stops the runtime.
- **Never switch modes in place.** Close the managed session and release the current consumer before changing between headless and headed; release stops the owned runtime. A `runtime_mode_conflict` is a safety stop, not a reason to launch another browser against the same profile.
- **Authentication remains manual when required.** Never collect or fill credentials, copy cookies, or manipulate tokens. If Webflow expires the dedicated session, start headed, let the user sign in directly, verify the dashboard, then return to headless mode.

The normal concurrency model is therefore: the user browses in normal Chrome while agent-browser controls the dedicated profile headlessly. Running the user and agent against the same profile at the same time is unsupported.

Attaching to a user-owned live tab is an exceptional shared-session mode for unsaved or collaborative state that cannot be reproduced in the dedicated profile. Obtain explicit authorization, ask the user to pause interaction for the duration, preserve every tab, and release control immediately afterward. Do not describe this exceptional mode as concurrent personal browsing.

## Choose a mode

### Attached exploration and debugging

Use this mode for the agent-owned authenticated runtime, or exceptionally when an explicitly authorized user-owned tab contains unsaved, collaborative, selected, or otherwise live state that the dedicated profile cannot reproduce.

1. Run `scripts/browser-runtime.py status`; require `endpointKind: direct_cdp`, `cdpReady: true`, and no conflicting consumer. Never use broker auto-connect in the routine workflow.
2. Claim the runtime's `agent_browser` lease, run `scripts/discover-designer-tabs.py --port <port>`, then connect through the selected transport. For `native`, use `sessionMode: "fresh"` and let the wrapper own the generated session. For `cli`, use the CLI's current managed session and do not create an unrelated named session.
3. Before claiming a shared tab, run the ownership diagnostic for its exact sanitized URL. For `native`, first use native session/tab observation to create the helper's sanitized `--ownership-fixture`; never shell out to the CLI to infer ownership of native-wrapper sessions. For `cli`, the helper may inspect CLI sessions directly. Reuse the current owning session or hand control back to the orchestrator when another known session owns it.
4. In headless mode, expect the first tab to be `about:blank` and navigate it to the exact approved Designer URL. In headed or exceptional shared-tab mode, run `tab`, identify the exact Designer tab by URL, and switch to its stable tab ID without navigating or reloading first.
5. Preserve all pre-existing tabs and browser state. Do not call `close`, clear storage, save/export state, or mutate the canvas without explicit task authorization. In exceptional user-owned attachment mode, require the user to pause browsing until control is released.

CDP exposes the dedicated authenticated browser to local control. Keep it loopback-only. Chrome DevTools MCP remains disabled during routine work and may be used only through an explicit exceptional handoff after agent-browser releases ownership.

### Isolated verification

Use this mode for repeatable checks where live unsaved state is not required.

1. Open the exact URL with the selected transport. For `native`, use `sessionMode: "fresh"`; for `cli`, choose one task-owned name and pass it as `--session <name>` to every action and cleanup command.
2. Use a dedicated session or profile. Make authentication setup explicit; never imply the isolated session shares the live tab's canvas state.
3. For local Designer, use the selected automation browser's native identity and `--ignore-https-errors` when the certificate requires it. Do not spoof the user agent merely because intentional headless Chrome reports `HeadlessChrome`; supply `--user-agent` only when a separately proven environment constraint requires it.
4. Fix viewport, selectors, setup, and assertions so reruns exercise the same state.
5. Close only the isolated session that this task owns.

Use `scripts/designer-session.py isolated --transport <native|cli> --url '<exact-url>' --surface '<selector>' --dry-run` to inspect the bounded action and cleanup plan before launch.

Do not print, export, persist, or commit cookies, tokens, credentials, storage state, or PII. State files are sensitive plaintext unless separately encrypted, so avoid them unless the task explicitly requires controlled persistence.

## Always clean up browser ownership

Treat cleanup as a required `finally` block, including failed and interrupted browser tasks:

1. Close the selected transport's managed browser session: native `agent_browser close` or CLI `agent-browser close`.
2. Run `scripts/browser-runtime.py release --consumer agent_browser`. Release removes the lease and stops the owned Chrome for Testing process and watchdog.
3. Run `scripts/browser-runtime.py status` and require `runtimeOwned: false`, `cdpReady: false`, `consumer: null`, and `status: stopped` before reporting completion.
4. If normal release is unavailable, run `scripts/browser-runtime.py stop`; it may terminate only PIDs that match the private runtime state and dedicated profile.

Never leave cleanup for the next browser task. Never kill unverified Chrome, Chromium, or agent-browser PIDs. The watchdog is an abnormal-exit backstop, not a substitute for immediate cleanup.

## Operate with compact evidence

1. **Observe narrowly.** Start with `snapshot -i -c -s "<surface>"`. Use a stable Designer selector, dialog, panel, or frame-owned surface. Escalate to depth-limited or full snapshots only when the narrow view cannot answer the question.
2. **Use fresh refs.** Treat `@eN` refs as valid only for the tab, frame, and latest relevant snapshot. Take a fresh snapshot after navigation, frame changes, reloads, or substantial UI updates.
3. **Batch dependent work.** Use `batch --bail` for a short sequence such as wait, snapshot, action, and targeted observation. Do not batch across an unknown state transition that needs inspection.
4. **Compare changes.** Capture the scoped baseline, perform one authorized action, then run `diff snapshot --selector "<surface>" --compact`. Prefer semantic state assertions before screenshots.
5. **Escalate evidence deliberately.** Use `get`, `eval`, console, errors, or network inspection for a specific question. Use screenshots for layout, placement, color, transformed canvas content, or final visual proof.

Native-tool example (use the same `batch` arguments via the CLI when `cli` is selected):

```json
{
  "args": ["batch", "--bail"],
  "stdin": "[[\"wait\",\"[data-automation-id=left-sidebar-component-browser-button]\"],[\"snapshot\",\"-i\",\"-c\",\"-s\",\"[data-automation-id=component-browser]\"]]"
}
```

Quote commands and selectors according to the current CLI help. Never put secrets in command arguments or output.

## Inspect frames and diagnostics

- Run `tab` before acting in an attached browser.
- Run `eval` to list frame URLs without returning page content or secrets, then use `frame <selector>` and take a new scoped snapshot. Return with `frame main`.
- Choose one canonical canvas frame for pass or fail decisions; Designer can expose duplicate same-origin canvas frames.
- Use stable `data-automation-id` readiness selectors instead of `networkidle`.
- Use `console`, `errors`, filtered `network requests`, request detail, metadata-only HAR, trace, or profiler only when each artifact answers the current diagnostic question.
- Keep HAR content disabled by default because request and response bodies can contain credentials or PII.
- Use screenshots only after inspecting them. Redact or omit sensitive content and store temporary evidence outside repositories.

Read [references/designer-workflows.md](references/designer-workflows.md) for Designer readiness, frames, local environment, TLS, visual checks, and evidence rules. Read [references/connected-apps.md](references/connected-apps.md) only for Campaign, Marketo, HubSpot, or another connected-app flow.

## Evidence contract

Report:

- mode, exact sanitized URL, observed ownership boundary, and target frame
- environment and readiness checks
- narrow before and after semantic observations
- authorized actions performed
- console, page-error, and filtered request findings when relevant
- inspected screenshot, trace, profile, or HAR paths with sensitive data excluded
- blockers and assumptions that were not validated
- cleanup proof showing the managed session closed and the owned runtime stopped

Do not treat an attached exploration as repeatable isolated verification. Do not treat an isolated pass as proof of the user's unsaved live canvas state.

## Compound after every use

Treat each completed run as input to the skill's next version. Read [references/compounding-loop.md](references/compounding-loop.md), reconstruct the complete sanitized run, and perform its automation review before the final response, even when the browser task passed cleanly.

Prefer executable helpers and tests over additional prose. Extend an existing helper before adding another. A browser run may queue a sanitized candidate, but it must not generate, modify, or execute new helper code during that same run. Promotion requires repeated deterministic evidence and a separate reviewed maintenance pass. Never persist site-specific IDs, URLs, credentials, tokens, cookies, PII, raw DOM, or customer content.

When the evidence queue marks a reusable deterministic opportunity for review:

1. Implement or extend the narrow helper in `scripts/`.
2. Add a focused test that reproduces the observed input and expected sanitized output.
3. Validate `capabilities.json`, run the helper and focused tests, and update the catalog entry.
4. Update `SKILL.md` or one direct reference only when routing or a non-obvious invariant changed.
5. Report the helper created or extended and the browser steps it replaces. Never promote more than one candidate per maintenance pass.

Report `Compounding: no promotable deterministic sequence found` only after every inventoried event is covered by a classified candidate and every candidate is `observe` or `do_not_persist`. Do not add speculative abstractions, fallback branches, or prose for a one-off observation.
