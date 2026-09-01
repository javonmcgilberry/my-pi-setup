---
name: webflow-designer-agent-browser
description: Webflow Designer browser work. Use for change validation, exact Designer URLs, authenticated or collaborative tabs, local app, iframe, or canvas debugging, visual QA, and agent-browser or CDP sessions.
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
4. Check the sessionless Auth Vault list. Use the explicitly configured
   dedicated Webflow profile when it is ready; otherwise report the blocker and
   use the headed [authentication gate](#authenticate-the-dedicated-profile)
   only with user authorization.
5. For local runs, recover only the declared HUD tasks and reconcile any stale
   dedicated Chrome process before retrying the browser operation.
6. Prepare the runtime and declare the exact target. Omit `checks` to use the
   documented service defaults; pass `authProfile` only for the identified Vault
   profile.
7. Execute the returned actions in order; Auth Vault login, when requested,
   precedes opening the exact Designer URL.
8. Classify the observed URL/title, then verify the Designer document and all
   readiness checks.
9. Choose the fast lane for read-only observation or the guarded lane for
   stateful or uncertain work.
10. Perform only the authorized interaction.
11. Finish the owned runtime, prove that it stopped, then retire the automation
   session.

The lifecycle can be driven by a host integration or directly from a shell.
Native `agent_browser` returns compact structured results when available; the
`agent-browser` CLI remains the fallback. `scripts/designer-code-mode.py`
is the Pi compatibility adapter for the same core used by
`bin/webflow-browser`; the direct helpers remain available for diagnostics and
CLI plans. A Playwright, Selenium, or other transport adapter is not included.

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
Before preparing an isolated run, use the native tool without a session (or the
CLI without `--session`) to list Auth Vault names:

```text
native agent_browser args: ["auth", "list"]
CLI: agent-browser auth list
```

When the private benchmark Auth Vault config is available, the equivalent
bounded check is:

```sh
node "$SKILL_DIR/scripts/designer-load-auth.mjs" status "$AUTH_CONFIG"
```

Continue only when its `classification` is `auth_profile_ready`; a missing or
failed check is an authentication blocker. Keep the result transient.

Use `authProfile` only when the user or private setup has identified one exact,
dedicated Webflow profile. Never choose the first profile, expose the list in a
report, or treat a saved Vault entry as proof that the site session is valid.
When that profile is selected, `prepare` emits `auth login <authProfile>` after
the owned runtime connects and before it opens the exact target. The login
result is only an authentication attempt; `verify` must still observe the exact
non-login Designer surface.

If no identified Vault profile is present, report `auth_profile_missing`; if the
Vault check itself fails, report `auth_vault_unavailable`. Stop unless the user
authorizes the headed fallback. For a new, reset, or expired dedicated profile:

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
standalone JSON protocol. Outside Pi, call
`$SKILL_DIR/bin/webflow-browser`; Pi's protocol uses the compatibility adapter
at `scripts/designer-code-mode.py`. Both use the deep lifecycle module in
`lib/webflow_browser`, which owns deterministic validation, runtime leases,
readiness, and cleanup. `SKILL.md` remains the source of judgment,
authorization, interaction lanes, and orchestration.

The operation declares the exact target, surface, transport, and mode.
`checks` is optional: when omitted, Code Mode probes `https://wfdev.io:8443/`
for both `hud` and `designer_service`, then probes `target_http` against the
exact target. It starts the managed Chrome for Testing runtime only after
proving that no live runtime owner is present, claims the exclusive
`agent_browser` lease, and returns the browser actions.

The managed profile is separate from the user's normal Chrome profile. Never
launch normal Chrome, attach to its profile, copy its credentials, or use a
profile path from another browser task. Manual headed startup is reserved for
login, MFA, and visual debugging. See [standalone CLI](references/standalone-cli.md)
for bootstrap and recovery commands.

If either default service probe fails, report that named blocker instead of
guessing another port or endpoint. Always probe `target_http` against the exact
requested Designer URL.

## Recover local launch prerequisites

The HUD's `designer` umbrella task may intentionally report `exited/up` because
its command is `true` and its dependency health is the meaningful signal. Do
not restart that meta-task solely because it is exited. For a repeatable launch,
pass only the configured concrete tasks to the recovery helper:

```sh
python3 "$SKILL_DIR/scripts/ensure-hud-tasks.py" ensure \
  --repo /path/to/webflow \
  --task server \
  --task wf-proxy \
  --task entrypoints/designer/client
```

The helper starts stopped/exited clients, stops and starts a running unhealthy
client, polls every selected task, and fails closed unless each selected task
reports `running/up` or the HUD-authoritative `exited/up` meta-task state. It
never starts a preset or touches an unlisted task. The benchmark preflight
uses this same helper before reporting HUD readiness.

If Auth Vault or browser startup reports a profile-lock failure, first inspect
the exact dedicated profile and then confirm cleanup only when the classifier
reports an orphan:

```sh
python3 "$SKILL_DIR/scripts/reconcile-chrome-profile.py" reconcile \
  --profile "$DEDICATED_PROFILE"
python3 "$SKILL_DIR/scripts/reconcile-chrome-profile.py" reconcile \
  --profile "$DEDICATED_PROFILE" --confirm
```

This command accepts only profiles below the skill's dedicated profile root,
recognizes only verified Chrome for Testing bundles, treats a live
`agent-browser` owner as active, and removes only stale singleton symlinks
after the matching orphaned process tree stops. It never terminates normal
Chrome, an unknown profile owner, or an active dedicated browser. The
benchmark Auth Vault wrapper invokes the confirmed pass once after a failed
Vault operation; a remaining active or unknown owner stays a blocker.

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

After readiness, choose an interaction lane. A lane describes the authorized
browser work; it does not replace the attached/isolated mode, transport, or
transaction lifecycle.

Use the **fast lane** for observation only. The exact target, authentication,
ownership boundary, and all five readiness checks must already be verified.
Keep the work scoped to snapshots, screenshots, visible text, layout, spacing,
color, and bounded diagnostics that do not include bodies or sensitive data.
The preparation handoff may run the selected Auth Vault login and open the exact
target; once the fast lane starts, do not navigate, select, or edit.
An attached tab also needs explicit attachment authorization and a paused user.

Use the **guarded lane** before navigation, reload, selection changes, canvas
edits, undo, redo, publish, connected-app actions, or any account, security, or
privacy change. It also applies to shared or customer surfaces and whenever the
target, owner, effect, or ability to change state is uncertain. Capture a small
baseline, obtain the required authorization, perform one bounded action, and
verify its postcondition and unrelated state.

Start in the fast lane only when every eligibility condition is proven.
Escalate before the first state-changing action. Keep the current transport and
owned transaction when the guarded work fits their approved scope; otherwise
finish cleanly and prepare a new guarded transaction. Never downgrade guarded
work to avoid authorization. An unclassified action is guarded or blocked.

Both lanes keep the same target, authentication, ownership, privacy, evidence,
and cleanup requirements. Fast-lane work cannot change state, so it does not
need a mutation baseline or mutation authorization. It still requires
readiness and stopped-runtime proof.

- Preserve the full approved URL, including `pageId`, `simulateRole`, host, and
  port. Reject credentials and secret-bearing query parameters.
- Do not snapshot during `prepare`. First classify the compact URL/title result
  and complete `verify`; only then take a scoped interactive snapshot. Treat
  refs as valid only for the latest snapshot of the same tab and frame.
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

After an interruption, use `browser-runtime.py status` for the managed runtime.
Use `reconcile-chrome-profile.py` only for the safe stale profile state it
identifies. Never infer that a lease is stale from a missing receipt, and never
terminate an unknown listener, profile owner, or replacement runtime.

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

## Validate current Webflow changes

Use this branch for the normal end-of-work request, "Validate my current
Webflow changes." Corpus discovery and manual Playwright command assembly are
maintenance tasks, not prerequisites.

For a short user-facing route and receipt guide, read
[change validation guide](references/change-validation-guide.md). For the
offline evidence compiler, contract rules, receipt semantics, and PICO design
rationale, read [evidence compiler architecture](references/evidence-compiler-architecture.md).

1. Route the change set. Call `webflow_designer` with
   `operation:"validate_change"`, the read-only Webflow `repoPath`, and
   `phase:"route"`. Without `changedFiles`, routing includes staged, unstaged,
   and bounded untracked files after the tracked exclusion list is applied.
   Every remaining file participates in routing. This step is complete when
   the response has a receipt and one route status.
2. Follow that status:
   - For `ready` with `mode:"trusted"`, call `phase:"execute_trusted"`. The
     tracked policy supplies every fixed runner and its AWS requirement. This
     branch is complete when execution returns a terminal receipt.
   - For `approval_required`, build one data-only contract from the returned
     `proposalContext`, then call `phase:"submit_candidate"`. Call
      `phase:"execute_candidate"` with the exact approval digest and omit
      confirmation fields. The host displays the action graph, evidence,
      target, semantic oracle, cleanup, and budget, then issues a one-time
      host confirmation token only after the user approves. Code Mode consumes
      that token before the run. This branch is complete when the user
      declines or the approved run returns a terminal receipt.
   - For `insufficient_evidence` or `routing_ambiguous`, report the named gap.
     This branch is complete when the response states that this workflow did
     not validate the change.
3. Report the result. Only `passed` is a successful validation. `ready` records
   routing only. Include the receipt's contracts, tests, cleanup state, and
   `failureClass` when present. A failed runner never proves cleanup: `proved`
   appears only after a successful fixed runner, `not_proved` records an
   interrupted or otherwise incomplete run, and `failed` identifies a teardown
   failure. Include `ignoredFiles` from the change set so the user can see what
   routing skipped.

A candidate contains bounded data: reviewed operation references, reviewed
locator keys, one fixed adapter, a semantic oracle, and adapter teardown. Pi
collects approval for one exact run. Candidate success produces evidence but
does not change the tracked policy or corpus.

Pi is the preferred host, not a requirement. Outside Pi, follow the
[standalone change-validation reference](references/standalone-cli.md#change-validation).
The standalone command validates the same contract, records the same one-run
state, displays the bounded plan, and requires the user to type the full
approval digest in an interactive terminal.

## Use curated test knowledge

During skill maintenance, corpus discovery, operation-card lookup, or
scenario-backed validation planning, read
[Test knowledge maintenance](references/test-knowledge-maintenance.md).
Normal browser work and end-of-work change validation do not use this branch.
