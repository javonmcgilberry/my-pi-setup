# Designer workflows

Read this reference after the main workflow when the task involves local
services, iframes, canvas assertions, screenshots, or diagnostics.

## Transaction handoff

The normal sequence is:

```text
prepare -> browser interaction -> verify -> authorized work -> finish
```

`prepare` performs the declared service probes, starts or reuses the managed
Chrome for Testing runtime, and claims the exclusive browser lease. The browser
transport performs page interaction. `verify` accepts compact surface evidence
and permits work only when the transaction still owns the expected runtime and
all readiness conditions pass. `finish` closes the session, releases the lease,
stops only the owned runtime, and proves the stopped state.

The private receipt binds the transaction to the runtime PID, start generation,
and lease token. A replacement process or unknown listener cannot satisfy an
older transaction. Use `status` after an interruption; use `reconcile` only for
the stale states that the classifier marks safe to converge.

The five readiness names are:

- `hud`: the declared HUD service responds.
- `designer_service`: the required Designer service responds.
- `target_http`: the exact target responds without connection refusal or a
  gateway failure.
- `browser_profile`: the managed Chrome for Testing profile is ready.
- `designer_surface`: the approved Designer document is authenticated, not a
  login document, and not a Chrome error page.

The service probe request normally contains `hud`, `designer_service`, and
`target_http`. The runtime and surface checks are produced during the browser
handoff. `auth_required`, `unavailable`, and `error` block QA.

## URL and environment

- Preserve the exact URL, including `pageId`, `simulateRole`, host, and port.
- Allow only approved Designer or local development hosts. Reject credentials
  and sensitive query parameters.
- Use Chrome for Testing's native identity. Intentional headless runs report a
  `HeadlessChrome` user agent; do not replace it with a headed identity unless a
  reproduced environment problem requires that change.
- Use `--ignore-https-errors` for local HTTPS only when the local certificate
  requires it. The session helper adds this flag for loopback targets.
- Declare every expected local listener or HTTP endpoint before changing
  selectors. An empty shell, login redirect, `502`, `504`, or missing extension
  server is an environment or authentication signal until proven otherwise.
- For a local published page returning `500`, run
  `scripts/published-site-preflight.py` before debugging product code. Restore
  the existing renderer service before treating the result as a product bug.
- Do not wait for `networkidle`; Designer and extensions keep background
  requests open.

## Surfaces and frames

Readiness needs the exact URL, a Webflow Designer title or the observed
`Webflow - <site>` title on an approved Designer origin, a non-login document,
and no Chrome error page. A fixed sidebar selector is not a readiness check.

After readiness:

1. Scope the snapshot to the feature surface.
2. If the selector is absent from the main frame, enumerate frames and inspect
   the matching frame.
3. For an extension, match the expected origin and route, wait for an
   extension-owned selector, and take a fresh snapshot.

The canvas commonly lives in an iframe such as `/site/empty.html`. The parent
owns Designer panels, overlays, and selection UI. Duplicate canvas frames can
appear; choose one by URL, geometry, and target signal, then use that frame for
the pass or fail decision.

Capture parent evidence for placement and chrome state, then canvas or
extension evidence for the content. A transformed canvas crop can be blank or
dark even when the content is healthy, so pair semantic checks with a viewport
screenshot.

## Assertion order

1. Prove the expected environment, URL, tab, and frame.
2. Prove semantic state: text, counts, roles, data attributes, component IDs,
   field names, and selection state.
3. Perform the authorized action and compare the scoped state with the baseline.
4. Inspect a screenshot for layout, spacing, transformed content, or color.
5. For published parity, verify the runtime request and semantic result before
   comparing visuals.

When several controls match, use target text, data attributes, frame URL, and
geometry. A broad first match is not proof.

## Diagnostics

- Capture filtered `console` and page errors after the surface is ready.
- Filter network requests before opening request details. Use metadata-only HAR
  capture unless a reviewed diagnostic requires bodies.
- Use traces and profiles for lifecycle or performance questions. Keep them
  temporary.
- Use `eval` only in the confirmed frame and return a small sanitized object.
- Never return cookies, storage values, tokens, credentials, a full DOM dump,
  or the complete Designer API model.

## Evidence and ownership

Attached sessions start in the fast lane after attachment is authorized.
Navigation, reload, selection changes, canvas edits, undo, redo, publish, and
connected-app actions can change user or site state and require the guarded
lane.

The dedicated Chrome for Testing profile is the normal authenticated surface.
A user-owned live tab is exceptional. Obtain authorization, ask the user to
pause interaction, preserve every tab, and release control immediately after
the required observation.

Keep screenshots, JSON, HAR files, traces, and profiles outside the repository.
Sanitize URLs before reporting them. Record the ownership boundary, mode,
runtime mode, target frame, semantic observations, authorized actions, blockers,
and cleanup proof.
