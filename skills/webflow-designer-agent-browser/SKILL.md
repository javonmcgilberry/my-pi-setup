---
name: webflow-designer-agent-browser
description: Use agent-browser and Chrome DevTools Protocol to inspect, debug, and verify authenticated Webflow Designer sessions with compact snapshots, targeted evidence, and a self-compounding automation loop. Trigger for Designer URLs on design.webflow.com, design.wfdev.io, or wfdev.io; authenticated local Designer QA; extension iframes; canvas or visual debugging; agent-browser; CDP attachment; checks that must observe the user's current unsaved or collaborative Designer tab; and repeated browser work that should become a deterministic reusable helper.
---

# Webflow Designer Agent Browser

Use the best available agent-browser transport for token-efficient Designer exploration while preserving the exact browser state under test. Prefer native `agent_browser` when available; use the CLI fallback only when native is unavailable. This skill owns the repeatable Chrome-for-Testing lifecycle and the deterministic evidence loop; it does not attach to the user's normal Chrome profile.

## Deterministic transaction gate before Designer QA

For normal local or authenticated Designer QA, use the deferred Code Mode
`webflow_designer` command instead of spawning a separate model-driven setup
owner. Its bounded transaction is:

```text
prepare -> selected agent-browser interaction -> verify -> authorized work -> finish in finally
```

`prepare` receives the exact target, selected `native` or explicit `cli`
transport, attached or isolated mode, scoped selectors, and the three declared
service probes. It batches those probes, ensures the dedicated Chrome for
Testing runtime, claims the exclusive `agent_browser` lease, and returns the
transport-specific browser actions. It never invokes arbitrary native Pi tools.
The model still performs page interaction with native `agent_browser` when
available; the CLI is selected explicitly and cannot be substituted later.

`status` is a read-only bounded lifecycle classifier for interrupted or
partially cleaned runs. It reports whether the state is clean, an active
transaction, a valid direct/native owner, a stale receipt/lease that can be
reconciled, an environment-independent ownership conflict, or an unverified
listener. `reconcile` only converges the classifier's explicitly safe stale
states; it never steals a live direct/native owner or terminates an unverified
listener.

`verify` accepts only compact evidence: the exact sanitized URL, Webflow
Designer title (including the observed `Webflow - <site>` form on a Designer
origin), document classification, authentication boolean, error-page
boolean, and the selector observed. It derives the five required readiness
states and permits authorized work only when every state is `ready` while the
transaction still holds the lease. It classifies login or expired-auth state as
`auth_required`, not as a QA result. `finish` belongs in `finally` after the
selected browser session closes; it releases the lease, stops only the owned
runtime, proves the stopped state, and is safe to repeat.

The required check names remain `hud`, `designer_service`, `target_http`,
`browser_profile`, and `designer_surface`. A missing or failed service probe,
runtime conflict, transport mismatch, authentication-required surface, stale
lease, or unclean finish is a named blocker. Do not retry by switching
transport, copying credentials, repairing profiles, or repeatedly reloading.
The private transaction receipt binds the runtime PID/start generation and
lease token; a replacement process, nested profile symlink, or unknown listener
is never treated as the owned browser.

If Code Mode is unavailable, use the existing direct helpers with the same
check names and cleanup proof; this is an explicit fallback, not a second
transport hidden inside the custom command. `scripts/readiness-gate.py` remains
the small fail-closed classifier for standalone checks and held transactions.

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
4. For normal managed local/authenticated QA, complete `webflow_designer`
   `prepare` before browser interaction and `verify` before authorized work. Do
   not start a separate readiness or QA subagent. In the direct-helper fallback,
   run the same five checks before acting.
5. On `profile_unavailable`, fully quit normal Chrome, then run `scripts/browser-runtime.py bootstrap --confirm-sensitive-copy` once. The default source is the normal Chrome `Default` profile; pass `--source-profile <directory-name>` explicitly for another profile. Bootstrap excludes `Local State`, cookie databases, saved-login databases, and Web Data. Then run `start --headed` for a one-time Webflow login and `release --consumer agent_browser` immediately afterward.
6. Choose one mode explicitly and record it in the evidence.

## Reusable helpers

- Run `scripts/capability-catalog.py list [--category <name>]` for the compact deferred helper catalog. Read only the selected helper or direct reference; do not load every helper contract up front.
- Use the deferred Code Mode `webflow_designer` capability for `help`, exact or
  category-scoped capability lookup, `status`, `reconcile`, `prepare`, `verify`,
  and `finish`. Pass one
  JSON string with `JSON.stringify`; use `nextOffset` rather than dumping the
  catalog. The command owns lifecycle state, not page snapshots or native tool
  invocation.
- Run Code Mode `status` before recovering an interrupted transaction. Follow its
  bounded `action`: start only from `clean_stopped`, defer an active direct/native
  owner, and call `reconcile` only when it reports a safe stale state. Never
  infer that a lease without a Code Mode receipt is stale. For lower-level
  diagnostics, `scripts/browser-runtime.py status` still owns the dedicated
  profile, Chrome for Testing process, loopback direct-CDP readiness, bounded
  watchdog, and exclusive consumer lease. `ensure` is the idempotent headless
  default; use `start --headed` only for login, MFA, or visual debugging.
  `release` also stops the owned runtime. Use `plan`, `bootstrap`, `ensure`,
  `transfer-cookies`, `claim`, `release`, or `stop` only for the lifecycle phase
  each command names.
- Run `scripts/readiness-gate.py` for a direct-helper or diagnostic handoff when
  the Code Mode facade is unavailable. A held transaction uses its
  `--runtime-held` state; a standalone handoff still requires `--runtime-stopped`.
- The tracked `agent-browser-policy.json` keeps nested upstream `chat` and cookie transfer fail-closed. Ordinary deterministic browser calls are not restricted by the active Pi model or reasoning level. Override the policy only with an explicit `--policy /private/path/policy.json` or `PI_AGENT_BROWSER_POLICY_CONFIG=/private/path/policy.json`; never place cookie values or secrets in that file.
- Cookie transfer is a separate, two-factor opt-in. Enable `cookieTransfer.enabled` in a private policy override, verify the exact `allowedDomains`, then run `scripts/browser-runtime.py transfer-cookies --confirm-cookie-transfer` against an already-ready dedicated runtime while the `agent_browser` lease is held. Use `--dry-run` first; direct transfers require an exclusive `claim --consumer agent_browser`, then the returned private `leaseId` must be supplied to transfer and to matching release. The helper snapshots only the source Cookies database and sidecars, decrypts matching unexpired macOS Chrome cookies in memory through Keychain-derived material, injects them with loopback CDP `Network.setCookies`, and reports counts only. It never launches the source profile, copies a full profile, writes plaintext cookies, or transfers wildcard domains.
- Run `scripts/discover-designer-tabs.py` to query an existing CDP endpoint and return only sanitized Designer tab metadata. Use `--ownership-url` and `--current-session` to inspect known agent-browser ownership without claiming or focusing a tab.
- Run `scripts/discover-designer-tabs.py --attachment-config config/attachment.json --transport <native|cli>` from this skill directory before attaching. The tracked config emits the selected transport's explicit `connect <port>` action for canonical `direct_cdp`. Pass a sanitized surface fixture back with `--surface-fixture`, `--expected-title`, and the required actual `--expected-runtime-mode`; headed verification rejects `HeadlessChrome`, headless verification requires it, and both reject all-`about:blank` managed fallbacks.
- Run `scripts/designer-session.py <attached|isolated> --transport <native|cli>` to preflight a bounded bootstrap and emit transport-specific actions plus mandatory cleanup. It never launches a browser itself. Supply each required service through `--tcp-service` or `--http-service`; a failed preflight stops plan emission and identifies the unavailable label without exposing its target. Attached fallback plans also require the private `leaseId` returned by `browser-runtime.py claim`, so delayed cleanup cannot release a replacement runtime.
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
- **Headless is the routine default.** Run `scripts/browser-runtime.py ensure` for invisible, repeatable authenticated automation. The dedicated profile remains separate from the user's normal Chrome profile. The default watchdog limit is 1,800 seconds; use a larger bounded `--max-runtime-seconds` only when the task is expected to need it.
- **Headed is an explicit temporary mode.** Run `scripts/browser-runtime.py start --headed` only for manual login, MFA, user observation, or visual debugging. After that work, close the managed agent-browser session and release the consumer; release stops the runtime.
- **Never switch modes in place.** Close the managed session and release the current consumer before changing between headless and headed; release stops the owned runtime. A `runtime_mode_conflict` is a safety stop, not a reason to launch another browser against the same profile.
- **Authentication remains manual by default.** Never collect or fill credentials or manipulate tokens. If Webflow expires the dedicated session, start headed, let the user sign in directly, verify the dashboard, then return to headless mode. Cookie transfer is available only through the explicit policy-and-flag flow above.

The normal concurrency model is therefore: the user browses in normal Chrome while agent-browser controls the dedicated profile headlessly. Running the user and agent against the same profile at the same time is unsupported.

Attaching to a user-owned live tab is an exceptional shared-session mode for unsaved or collaborative state that cannot be reproduced in the dedicated profile. Obtain explicit authorization, ask the user to pause interaction for the duration, preserve every tab, and release control immediately afterward. Do not describe this exceptional mode as concurrent personal browsing.

## Choose a mode

### Attached exploration and debugging

Use this mode for the agent-owned authenticated runtime, or exceptionally when an explicitly authorized user-owned tab contains unsaved, collaborative, selected, or otherwise live state that the dedicated profile cannot reproduce.

1. For the normal agent-owned runtime, call `webflow_designer` `prepare` with
   `mode: "attached"`; require its direct-CDP, `browser_profile`, and lease
   receipt before connecting. Never use broker auto-connect in the routine
   workflow.
2. Execute the returned connect/tab actions through the selected transport. For
   `native`, use `sessionMode: "fresh"` and let the wrapper own the generated
   session. For `cli`, use the task-owned session returned by the plan and do
   not create an unrelated named session. For the exceptional authorized
   user-owned tab, keep the direct diagnostic path below and do not claim the
   dedicated runtime on its behalf.
3. Before claiming a shared tab, run the ownership diagnostic for its exact sanitized URL. For `native`, first use native session/tab observation to create the helper's sanitized `--ownership-fixture`; never shell out to the CLI to infer ownership of native-wrapper sessions. For `cli`, the helper may inspect CLI sessions directly. Reuse the current owning session or hand control back to the orchestrator when another known session owns it.
4. In headless mode, expect the first tab to be `about:blank` and navigate it to the exact approved Designer URL. In headed or exceptional shared-tab mode, run `tab`, identify the exact Designer tab by URL, and switch to its stable tab ID without navigating or reloading first.
5. Preserve all pre-existing tabs and browser state. Do not call `close`, clear storage, save/export state, or mutate the canvas without explicit task authorization. In exceptional user-owned attachment mode, require the user to pause browsing until control is released.

CDP exposes the dedicated authenticated browser to local control. Keep it loopback-only. Chrome DevTools MCP remains disabled during routine work and may be used only through an explicit exceptional handoff after agent-browser releases ownership.

### Isolated verification

Use this mode for repeatable checks where live unsaved state is not required.

1. Call `webflow_designer` `prepare` with `mode: "isolated"`, then open the
   exact URL using its returned action. For `native`, use `sessionMode: "fresh"`;
   for `cli`, pass the one task-owned name to every action and cleanup command.
2. Use a dedicated session or profile. Make authentication setup explicit; never imply the isolated session shares the live tab's canvas state.
3. For local Designer, use the selected automation browser's native identity and `--ignore-https-errors` when the certificate requires it. Do not spoof the user agent merely because intentional headless Chrome reports `HeadlessChrome`; supply `--user-agent` only when a separately proven environment constraint requires it.
4. Fix viewport, selectors, setup, and assertions so reruns exercise the same state.
5. Close only the isolated session that this task owns.

Use `scripts/designer-session.py isolated --transport <native|cli> --url '<exact-url>' --surface '<selector>' --dry-run` to inspect the bounded action and cleanup plan before launch.

Do not print, export, persist, or commit cookies, tokens, credentials, storage state, or PII. State files are sensitive plaintext unless separately encrypted, so avoid them unless the task explicitly requires controlled persistence. The cookie-transfer helper keeps decrypted values in memory and emits only counts and allowed domain names.

## Always clean up browser ownership

Treat cleanup as a required `finally` block, including failed and interrupted browser tasks:

1. Close the selected transport's managed browser session: native `agent_browser close` or CLI `agent-browser close`.
2. Call `webflow_designer` `finish` with the prepared transaction ID. It
   releases the exact `agent_browser` lease and stops the owned Chrome for
   Testing process and watchdog.
3. Require the command's stopped-state proof: `runtimeOwned: false`,
   `cdpReady: false`, `consumer: null`, `leasePresent: false`, and
   `status: stopped`.
4. If the facade is unavailable or reports a cleanup failure, first use the
   Code Mode classifier when available and call `reconcile` only for its safe
   stale classification. The direct helper remains an explicit fallback:
   `scripts/browser-runtime.py release --consumer agent_browser --lease-id <leaseId>`,
   then `status`; `stop` is the final bounded fallback and may terminate only
   PIDs that match the private runtime state and dedicated profile. A direct
   owner, replacement runtime, or unverified listener remains fail-closed.

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
  "stdin": "[[\"wait\",\"[data-automation-id=left-sidebar-add-button]\"],[\"snapshot\",\"-i\",\"-c\",\"-s\",\"[data-automation-id=left-sidebar-add-button]\"]]"
}
```

Quote commands and selectors according to the current CLI help. Never put secrets in command arguments or output.

## Inspect frames and diagnostics

- Run `tab` before acting in an attached browser.
- Run `eval` to list frame URLs without returning page content or secrets, then use `frame <selector>` and take a new scoped snapshot. Return with `frame main`.
- Choose one canonical canvas frame for pass or fail decisions; Designer can expose duplicate same-origin canvas frames.
- Use the exact URL, a Webflow Designer or `Webflow - <site>` title on a
  Designer origin, and a non-error document for readiness. Use stable
  `data-automation-id` selectors only for feature-specific assertions after readiness.
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
