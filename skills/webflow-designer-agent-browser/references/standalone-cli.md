# Standalone CLI

The standalone path exposes change-validation diagnostics and the managed
browser lifecycle. Native `agent_browser` is a host integration and is not
required here.

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

## Managed transaction

Use `designer-code-mode.py` when the run needs the prepare, verify, and finish
contract. It owns the runtime generation and lease. Send one JSON request at a
time and execute only the browser action it returns.

Check the protocol and interrupted-run state first:

```sh
CODE_MODE="$SKILL_DIR/scripts/designer-code-mode.py"
printf 'help\n' | python3 "$CODE_MODE"
printf '%s\n' '{"version":1,"operation":"status"}' \
  | python3 "$CODE_MODE"
```

Prepare an isolated CLI run with the real approved target and service checks.
When service endpoints are not supplied, use `https://wfdev.io:8443/` for both
`hud` and `designer_service`; report either failed default probe instead of
guessing another endpoint. The three service checks are required in the request. The helper derives
`browser_profile` after it starts the managed browser and leaves
`designer_surface` pending until verification.

```sh
DESIGNER_URL='https://design.webflow.com/?pageId=synthetic-page'
SURFACE='body'
READY_SELECTOR='body'
HUD_PORT=3000
DESIGNER_SERVICE_PORT=3001
SESSION='webflow-qa'

cat <<JSON | python3 "$CODE_MODE"
{
  "version": 1,
  "operation": "prepare",
  "transport": "cli",
  "mode": "isolated",
  "target": "$DESIGNER_URL",
  "surface": "$SURFACE",
  "readySelector": "$READY_SELECTOR",
  "session": "$SESSION",
  "checks": [
    {"name": "hud", "kind": "tcp", "host": "127.0.0.1", "port": $HUD_PORT},
    {"name": "designer_service", "kind": "tcp", "host": "127.0.0.1", "port": $DESIGNER_SERVICE_PORT},
    {"name": "target_http", "kind": "http", "url": "$DESIGNER_URL", "status": 200}
  ]
}
JSON
```

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
cat <<JSON | python3 "$CODE_MODE"
{
  "version": 1,
  "operation": "verify",
  "transactionId": "<transaction-id-from-prepare>",
  "transport": "cli",
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

Always finish, including after a failed action:

```sh
cat <<JSON | python3 "$CODE_MODE"
{
  "version": 1,
  "operation": "finish",
  "transactionId": "<transaction-id-from-prepare>",
  "transport": "cli"
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
  --session "$SESSION" \
  --url "$DESIGNER_URL" \
  --ready-selector "$READY_SELECTOR" \
  --surface "$SURFACE" \
  --tcp-service hud 127.0.0.1 "$HUD_PORT" \
  --tcp-service designer_service 127.0.0.1 "$DESIGNER_SERVICE_PORT" \
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
