# Standalone CLI

The standalone path exposes change-validation diagnostics and the managed
browser lifecycle. The deterministic lifecycle lives in the local
`lib/webflow_browser` package and is exposed through `bin/webflow-browser`.
Pi keeps its judgment, authorization, interaction lanes, and orchestration in
`SKILL.md`; `scripts/designer-code-mode.py` remains the compatibility adapter
used by the Pi-facing protocol. Native `agent_browser` is a host integration
and is not required to produce the lifecycle result.

## Lifecycle CLI

Use the CLI for shell automation, CI, or a non-Pi host. Each lifecycle command
reads at most one versioned JSON request from stdin and writes one sanitized JSON
result to stdout. The request envelope is described by
`schemas/webflow-browser-cli-request.schema.json`; the core still performs the
semantic validation for targets, modes, checks, and transaction state.

```sh
CLI="$SKILL_DIR/bin/webflow-browser"
"$CLI" --help
printf '%s\n' '{"version":1,"operation":"status"}' | "$CLI" status
```

The commands are:

- `prepare`: run service preflight, claim the owned runtime lease, and return
  the ordered browser actions.
- `verify`: recheck service and runtime identity, then classify the exact
  Designer surface.
- `status`: classify the current runtime, lease, and transaction without
  changing them. With no stdin, it uses the status request above.
- `reconcile`: recover only a stale lease or transaction state that `status`
  marks as safe to recover.
- `finish`: release the transaction and prove stopped-runtime cleanup.
- `cleanup`: alias for `finish`.

The CLI returns exit code `0` for a completed command, `1` for a lifecycle or
cleanup failure, `2` for an invalid command or request, `3` for a readiness or
authentication blocker, and `4` for an ownership or transaction conflict.
It returns browser actions but never executes them or emits credentials,
cookies, raw DOM, customer data, or full browser state.

The [architecture map](webflow-browser-cli-architecture.html) shows the old
script shape and the new core seam. The
[lifecycle map](webflow-browser-cli-lifecycle.html) shows command flow,
ownership, cleanup, and the split between Pi policy and standalone mechanics.

## Change validation

Use `validate-change.py` when Pi is unavailable, the user chooses another host,
or CI needs deterministic trusted routing. It reads the tracked policy;
runtime callers cannot replace that policy. All non-ignored changed files take
part in routing. The route output lists excluded lockfiles, TypeScript config,
and lint config under `ignoredFiles`. Run the repository's normal checks for
those files.

```sh
SKILL_DIR=/path/to/webflow-designer-agent-browser
python3 "$SKILL_DIR/scripts/validate-change.py" route \
  --repo /path/to/webflow
python3 "$SKILL_DIR/scripts/validate-change.py" execute-trusted \
  --repo /path/to/webflow --execute
```

`route` is complete when it returns the bounded change set, route, and receipt.
A `ready` receipt means a trusted runner exists but has not run.
`execute-trusted` is complete only when it returns a terminal receipt.
Only `passed` proves the fixed runner completed its semantic oracle and
teardown. Failed runs return a normalized `failureClass` and use `not_proved`
unless the runner specifically reports a teardown failure. Runner output never
appears in the receipt.

For an unknown route, inspect the bounded context with `proposal-context`.
After a model or engineer writes one data-only candidate contract, validate and
record it:

```sh
python3 "$SKILL_DIR/scripts/validate-change.py" validate-candidate \
  --repo /path/to/webflow \
  --candidate /path/to/contract.json
```

The result includes an `approvalDigest`. The user can then run the candidate
from an interactive terminal:

```sh
python3 "$SKILL_DIR/scripts/validate-change.py" execute-candidate \
  --repo /path/to/webflow \
  --candidate /path/to/contract.json \
  --approval-digest <approval-digest> \
  --execute
```

The command displays the exact evidence, target, actions, oracle, cleanup, and
budget. It runs only after the user types the full digest. The private state
file prevents a second run of the same approved candidate. A noninteractive
caller cannot execute a candidate.

## Browser requirements

The managed browser path uses Python, the helpers in `scripts/`, Chrome for
Testing, and the `agent-browser` CLI. These helpers do not provide a
Playwright, Selenium, or Puppeteer page adapter.

Verify the tools before claiming a runtime:

```sh
SKILL_DIR=/path/to/webflow-designer-agent-browser
python3 "$SKILL_DIR/scripts/browser-runtime.py" plan
agent-browser --version
```

The runtime helper selects an installed Chrome for Testing build and refuses to
fall back to normal Chrome. Keep the dedicated profile separate from a user's
normal browser profile.

The first profile bootstrap is the only flow that reads a normal Chrome
profile. Quit normal Chrome before running it. The helper excludes Local State,
cookie databases, saved-login databases, and Web Data from the copy. Complete
Webflow login with a dedicated, least-privilege test user in the headed managed
browser:

```sh
python3 "$SKILL_DIR/scripts/browser-runtime.py" bootstrap \
  --confirm-sensitive-copy
python3 "$SKILL_DIR/scripts/browser-runtime.py" start --headed
# Complete login in the visible Chrome for Testing window.
```

If the dedicated profile is already authenticated, reuse it without another
login prompt. Do not copy credentials, cookies, or account identifiers into a
command, report, or repository.

Before an isolated transaction, inspect the existing profile. If it is new,
reset, expired, or on a login page:

1. Start the dedicated runtime with `start --headed`.
2. Ask the user to sign in with a dedicated test user. Do not use an account
   whose session must remain active in another browser.
3. Wait for explicit confirmation, then verify a Designer or dashboard surface.
4. Keep that runtime open and prepare the isolated transaction against its CDP
   port. Do not close and restart Chrome between authentication and QA.

`profileInitialized` proves that profile files exist, not that Webflow auth is
valid. A login page, expired-auth page, or blank document blocks the run. An
authenticated surface can proceed without asking the user to log in again.

For an existing Auth Vault entry, run the sessionless list before preparing a
transaction and select only the exact dedicated Webflow profile identified by
the private setup:

```sh
agent-browser auth list
```

For the private benchmark configuration, the same check returns a compact
`classification` without page content:

```sh
node "$SKILL_DIR/scripts/designer-load-auth.mjs" status "$AUTH_CONFIG"
```

Proceed only for `auth_profile_ready`; keep the result out of durable reports.

Do not pass `--session` to this check or copy its output into a report. In the
managed transaction, pass that exact name as `authProfile`; Code Mode then emits
`auth login <authProfile>` after connecting and before opening the target. A
successful Vault login is not authentication proof: `verify` still requires the
exact non-login Designer surface. If the identified profile is absent, report
`auth_profile_missing`; if the check itself fails, report
`auth_vault_unavailable`. Use the headed gate only when the user authorizes it.

## Managed transaction

Use `bin/webflow-browser` when the run needs the prepare, verify, and finish
contract outside Pi. It owns the runtime generation and lease through the
shared core. Send one JSON request at a time and execute only the browser
action it returns. Pi uses the equivalent compatibility adapter at
`scripts/designer-code-mode.py`.

Check the protocol and interrupted-run state first:

```sh
CLI="$SKILL_DIR/bin/webflow-browser"
"$CLI" --help
printf '%s\n' '{"version":1,"operation":"status"}' \
  | "$CLI" status
```

Prepare an isolated native run with the real approved target. Native requests
must not contain the CLI-only `session` field. Omit `checks` to use
`https://wfdev.io:8443/` for both `hud` and `designer_service`, plus an exact
`target_http` probe; report a failed default probe instead of guessing another
endpoint. Add `authProfile` only when the preceding Auth Vault list identified
that exact dedicated profile. The helper derives `browser_profile` after it
starts the managed browser and leaves `designer_surface` pending until
verification.

```sh
DESIGNER_URL='https://design.webflow.com/?pageId=synthetic-page'
SURFACE='body'
READY_SELECTOR='body'
AUTH_PROFILE='webflow-designer-benchmark'

cat <<JSON | "$CLI" prepare
{
  "version": 1,
  "operation": "prepare",
  "transport": "native",
  "mode": "isolated",
  "target": "$DESIGNER_URL",
  "surface": "$SURFACE",
  "readySelector": "$READY_SELECTOR",
  "authProfile": "$AUTH_PROFILE"
}
JSON
```

Remove the `authProfile` line when no exact dedicated Vault entry is
configured; then stop for the headed authentication gate rather than guessing
credentials or a different profile. The action list is already the contract:
execute `connect`, optional `auth login`, exact-target `open`, and `wait` in
order. Preparation never emits a snapshot.

Use the returned `actions` in order. The first action connects to the runtime
owned by the transaction; the isolated plan then opens the approved target in
that same browser. The CLI plan includes the task-owned session name. Do not
replace it with a guessed command or a different session. The prepare result
includes a `transactionId` and ordered cleanup instructions; retain both until
finish.

For an attached run, change `mode` to `attached` and keep the same transport.
The returned action connects to the managed loopback CDP endpoint. Use attached
mode only when the required state is live and cannot be reproduced in
isolated mode.

After the browser action, send compact surface evidence to `verify`:

```sh
cat <<JSON | "$CLI" verify
{
  "version": 1,
  "operation": "verify",
  "transactionId": "<transaction-id-from-prepare>",
  "transport": "native",
  "surface": {
    "url": "https://design.webflow.com/?pageId=synthetic-page",
    "title": "Webflow - Example site",
    "document": "designer",
    "authenticated": true,
    "errorPage": false,
    "scope": "body",
    "scopeObserved": true
  }
}
JSON
```

Proceed only when verification reports a ready Designer surface and permits
the requested work. If it reports `auth_required`, `unavailable`, or `error`,
stop and resolve that named blocker. Do not weaken the check or continue on a
login or Chrome error page.

Only after URL/title classification and successful `verify` may the browser
take a scoped snapshot. The direct helper's snapshot is opt-in with
`--include-snapshot`; the Code Mode preparation plan never enables it. Do not
capture or report a login-page DOM.

Always finish, including after a failed action:

```sh
cat <<JSON | "$CLI" finish
{
  "version": 1,
  "operation": "finish",
  "transactionId": "<transaction-id-from-prepare>",
  "transport": "native"
}
JSON
```

The finish result must prove `runtimeOwned: false`, `cdpReady: false`,
`consumer: null`, `leasePresent: false`, and `status: stopped`. A failed or
interrupted finish is a blocker. Check `status` before attempting recovery;
`reconcile` is safe only when the classifier reports a stale state that it can
converge without taking ownership from another process.

After successful finish, run the returned `retireAfterFinish` action to close
the native or CLI automation session. Never run that close action first: on a
raw CDP connection it can terminate the runtime instead of only disconnecting.
Cleanup never signs out, clears cookies, or resets the dedicated profile.

## Direct helper checks

Use `designer-session.py` for a preflight and action plan when the full JSON
facade is not needed. `--preflight-only --dry-run` does not open a browser:

```sh
python3 "$SKILL_DIR/scripts/designer-session.py" isolated \
  --transport cli \
  --session 'webflow-qa' \
  --url "$DESIGNER_URL" \
  --ready-selector "$READY_SELECTOR" \
  --surface "$SURFACE" \
  --tcp-service hud 127.0.0.1 3000 \
  --tcp-service designer_service 127.0.0.1 3001 \
  --http-service target_http "$DESIGNER_URL" 200 \
  --preflight-only --dry-run
```

Use `readiness-gate.py` for a standalone diagnostic handoff only after the
runtime state is known. A stopped runtime is cleanup proof for a standalone
handoff; a held runtime is valid only while the exact lease is owned:

```sh
python3 "$SKILL_DIR/scripts/readiness-gate.py" \
  --check hud=ready \
  --check designer_service=ready \
  --check target_http=ready \
  --check browser_profile=ready \
  --check designer_surface=ready \
  --runtime-stopped
```

An attached direct-helper plan also requires the exact lease ID returned by
`browser-runtime.py claim`. Pass that ID to the plan and to release. Do not
release an unnamed lease or one belonging to a replacement runtime.

For a recorded run, generate a mode-specific report template, replace its
placeholders with sanitized evidence, and validate it:

```sh
python3 "$SKILL_DIR/scripts/automation-evidence.py" \
  --report-template isolated > /tmp/webflow-evidence.json
python3 "$SKILL_DIR/scripts/automation-evidence.py" \
  --validate-report /tmp/webflow-evidence.json
```

Keep temporary reports outside the repository and remove them after review.
