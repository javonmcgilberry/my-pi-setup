---
name: webflow-designer-agent-browser
description: Inspect, debug, and verify authenticated Webflow Designer sessions, local Designer apps, extension iframes, and canvas state with isolated or attached browser runs. Use for Designer URLs, unsaved or collaborative tabs, iframe and canvas debugging, visual QA, CDP, and agent-browser workflows. Choose the native agent_browser integration when available or the agent-browser CLI for standalone runs.
---

# Webflow Designer browser workflow

Designer can show a login page, an error document, an empty shell, or the
wrong iframe while a browser command succeeds. Local extensions also depend on
their exact origin and running services. A live tab may contain unsaved or
collaborative state that an isolated browser cannot reproduce. This workflow
checks the target before interaction, keeps browser ownership clear, limits
captured data, and proves cleanup.

## Use the workflow

1. Choose [attached or isolated mode](#choose-a-mode).
2. Select one [browser transport](#select-a-transport) before starting.
3. Obtain the exact Designer URL. Ask for it when it is missing; never infer a
   target from a default host or an unrelated open tab.
4. Complete the [authentication gate](#authenticate-the-dedicated-profile)
   before the first isolated run.
5. Prepare the runtime and declare the target and service checks.
6. Open or connect to the exact Designer URL, then inspect a narrow surface.
7. Verify the Designer document and all readiness checks.
8. Perform only the authorized interaction.
9. Finish the owned runtime, prove that it stopped, then retire the automation
   session.

The lifecycle can be driven by a host integration or directly from a shell.
Native `agent_browser` returns compact structured results when available; the
`agent-browser` CLI remains the fallback. `scripts/designer-code-mode.py`
provides the same JSON protocol for either path, and the direct helpers remain
available for diagnostics and CLI plans. A Playwright, Selenium, or other
transport adapter is not included.

## Choose a mode

**Isolated** mode is the default for repeatable checks. Use the dedicated
managed profile with a dedicated, least-privilege Webflow test user. The profile
keeps its authentication between runs, so do not ask the user to sign in again
when an authenticated Designer or dashboard surface is already visible. Do not
treat the result as proof of another tab's unsaved state.

**Attached** mode is for a selected live state that cannot be reproduced. The
dedicated managed runtime is the normal attached surface. Attaching to a
user-owned Chrome tab is exceptional: obtain explicit authorization, preserve
all tabs, ask the user to pause interaction, and release control immediately
after the observation.

## Authenticate the dedicated profile

An isolated run never opens a target in a fresh profile with unknown auth state.
For a new, reset, or expired dedicated profile:

1. Start the dedicated Chrome for Testing runtime in headed mode.
2. Ask the user to authenticate a dedicated test user. If the proposed account
   must remain active in another browser, stop and offer attached mode instead.
   Never fill credentials, copy cookies, or record the account identifier.
3. Wait for the user's confirmation that authentication is complete.
4. Verify a Webflow Designer or dashboard surface. A login page, expired-auth
   page, or blank document remains `auth_required`.
5. Keep that same managed runtime open for the prepared run. Connect the
   browser transport to it, then open the approved target.

Do not use `profileInitialized` as proof of authentication. If the user does
not confirm the first login checkpoint, stop before opening the requested
target. On later runs, inspect the existing profile first and continue without a
login prompt when it is still authenticated. An explicitly authorized attached
tab uses its existing authenticated state and does not copy that state into the
dedicated profile. Never sign out, clear cookies, or reset authentication as
part of cleanup.

## Select a transport

Select once and keep the choice through cleanup:

- Use native `agent_browser` when the host exposes and can call it.
- Otherwise use the `agent-browser` CLI with a task-owned session name.
- If neither is available, stop with `browser_transport_unavailable`.

Do not switch transports after preparation. Native and CLI sessions have
different ownership records, so switching can leave one session open or create
a second browser.

Before native preparation, confirm that the host tool is registered and
callable. If it is unavailable, stop before claiming the runtime rather than
starting another browser. A lease reserves the managed runtime for the handoff;
it does not prove that the native wrapper connected.

## Prepare the browser

For normal local or authenticated QA, use the lifecycle facade or the
standalone JSON protocol. The operation declares the exact target, surface,
transport, mode, and the three service probes: `hud`, `designer_service`, and
`target_http`. It starts or reuses Chrome for Testing, claims the exclusive
`agent_browser` lease, and returns the browser actions.

The managed profile is separate from the user's normal Chrome profile. Never
launch normal Chrome, attach to its profile, copy its credentials, or use a
profile path from another browser task. Manual headed startup is reserved for
login, MFA, and visual debugging. See [standalone CLI](references/standalone-cli.md)
for bootstrap and recovery commands.

When service endpoints are not supplied, probe `https://wfdev.io:8443/` for
both `hud` and `designer_service`. If either default probe fails, report that
named blocker instead of guessing another port or endpoint. Always probe
`target_http` against the exact requested Designer URL.

## Verify readiness

The five readiness checks are:

- `hud`: the declared HUD service responds.
- `designer_service`: the required Designer service responds.
- `target_http`: the exact target responds without a connection or gateway
  failure.
- `browser_profile`: the managed Chrome for Testing profile is ready.
- `designer_surface`: the tab has a Webflow Designer title on an approved
  Designer origin, shows a non-login document, and is not a Chrome error page.

`auth_required`, `unavailable`, and `error` are blockers, not QA results. A
fixed sidebar control is not a readiness check because Designer shells vary by
role. Verify the surface with compact evidence before any authorized work.

## Inspect and act

- Preserve the full approved URL, including `pageId`, `simulateRole`, host, and
  port. Reject credentials and secret-bearing query parameters.
- Start with a scoped interactive snapshot. Treat refs as valid only for the
  latest snapshot of the same tab and frame.
- Prove semantic state before taking a screenshot. Use screenshots for layout,
  transformed canvas content, spacing, or color.
- Treat attached sessions as read-only until the task authorizes navigation,
  selection changes, canvas edits, undo, redo, publish, or app actions.
- Before a mutation, capture a small baseline and verify that unrelated state
  did not change.
- Keep console, request, trace, and screenshot artifacts temporary and outside
  the repository. Do not return cookies, storage, tokens, credentials, raw
  DOM dumps, full Designer models, or customer data.

For iframe, local-service, assertion, and diagnostic details, read
[Designer workflows](references/designer-workflows.md). For connected-app
state, read [Connected apps](references/connected-apps.md) before acting.

## Finish every run

The runtime helper owns Chrome. The browser transport only connects to it. Put
cleanup in a `finally` path and keep this order:

1. Call `webflow_designer finish`, or release the exact standalone lease.
2. Confirm `runtimeOwned: false`, `cdpReady: false`, `consumer: null`,
   `leasePresent: false`, and `status: stopped`.
3. Only after that proof, close the selected native or CLI automation session.

Do not call `agent_browser close` while the managed runtime is still running.
For a raw CDP connection, `close` can terminate the browser instead of merely
disconnecting the transport.

After an interruption, use `status`. Run `reconcile` only for the safe stale
states it identifies. Never infer that a lease is stale from a missing receipt,
and never terminate an unknown listener or replacement runtime.

## Record evidence

For a recorded result, generate the mode-specific shape with
`scripts/automation-evidence.py --report-template attached` or
`--report-template isolated`, fill it with sanitized observations, and validate
it with `--validate-report <sanitized-report.json>`. Include the exact sanitized URL,
ownership boundary, target frame, readiness checks, before and after semantic
observations, authorized actions, relevant diagnostics, blockers, assumptions,
and the stopped-runtime proof.

Use [the automation maintenance loop](references/compounding-loop.md) only
during skill maintenance or when reviewing repeated automation opportunities. It is
not a required step after every browser task.

## Use curated test knowledge

The Webflow monorepo's Playwright and Cypress tests are evidence, not an
unrestricted instruction set. During skill maintenance, build a disposable,
commit-bound corpus index from the tracked policy:

```sh
tmp="$(mktemp -d)"
python3 scripts/test-corpus-index.py build \
  --repo /path/to/webflow \
  --output "$tmp/designer-corpus.json"
python3 scripts/test-corpus-index.py validate \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json"
python3 scripts/test-corpus-index.py lookup \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json" \
  --operation designer.page.switch
python3 scripts/test-corpus-index.py evaluate \
  --repo /path/to/webflow \
  --index "$tmp/designer-corpus.json"
```

The index extracts operation-level evidence and retains bounded provenance,
selectors, context, postconditions, confidence, utility, novelty, holdouts,
and negative evidence. Quarantined, skipped, stale, unsafe, or
fixed-duration-wait evidence cannot silently become positive executable
knowledge. The `evaluate` report checks held-out semantic assertions and
positive/holdout path separation without promoting a candidate. The source
commit and a source-file manifest must still match before lookup.

The same validated index is available through the `webflow_designer` Code Mode
operation `test_knowledge`: use `view:"status"` for compact freshness and
portfolio counts, or pass one `operationId` or capability `category` for a
bounded card lookup.

Scenario contracts are plan-only handoffs between an external test-data
adapter and the managed browser lifecycle:

```sh
python3 scripts/ensure-test-aws.py --repo /path/to/webflow
python3 scripts/test-scenario-eval.py plan \
  --scenario /path/to/scenario.json \
  --operation /path/to/operation-card.json \
  --dry-run
```

Run `ensure-test-aws.py` before scenario-backed local tests. It validates the
`dev-publish-only` profile without trusting inherited AWS variables, performs
`aws sso login --sso-session wf-session` only when required, checks the exact
temporary credentials held by every running `wf-app`, and restarts only the
`server` HUD task, which owns `entrypoints/server`, when those credentials are
missing or stale. If the server is not running, the preflight starts it.
Because `wf-app` hides its environment when it replaces its visible command
line, the check follows the process ancestry. The JSON output never includes
credential values. After a repair, the command stores only the server PID and
credential expiration in the private runtime directory. Later checks use that
receipt to avoid restarting a server that already has fresh credentials. Run
this preflight instead of researching the local AWS setup or starting a second
server.

This command does not run Playwright, create accounts, open a browser, or
execute generated shell text. Existing Webflow Playwright scenario helpers
own their browser contexts, so a future external adapter must explicitly
provide a sanitized Designer-target handoff and teardown artifact before a
managed `prepare -> interaction -> verify -> finish` run can use it. Do not
use a scenario plan as authorization to mutate a shared or customer surface.
