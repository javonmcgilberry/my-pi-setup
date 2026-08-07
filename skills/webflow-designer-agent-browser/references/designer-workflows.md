# Designer Workflows

## Two-stage readiness and QA handoff

Local/authenticated Designer testing has two serial owners:

1. A fresh setup/readiness subagent on the active default model at the highest available reasoning level inspects the HUD, starts only missing documented services, launches managed Chrome for Testing, verifies the exact authenticated Designer surface, then closes/releases the runtime.
2. A browser executor starts only after `readiness-gate.py` emits `qaLaunchAllowed: true`. It performs the requested assertions against the proven environment and owns final browser cleanup.

Never ask the QA executor to discover or repair the environment while it is also trying to test product behavior. Never overlap the two browser leases.

Classify readiness with exactly these bounded states:

- `hud`: the existing HUD is reachable.
- `designer_service`: the required Designer task is running.
- `target_http`: the exact target responds without connection refusal or gateway failure.
- `browser_profile`: managed Chrome for Testing starts with the dedicated profile.
- `designer_surface`: the exact authenticated tab renders the Designer readiness selector rather than login or `chrome-error://chromewebdata/`.

For a successful handoff, pass each as `ready` and include `--runtime-stopped`:

```sh
python3 scripts/readiness-gate.py \
  --check hud=ready \
  --check designer_service=ready \
  --check target_http=ready \
  --check browser_profile=ready \
  --check designer_surface=ready \
  --runtime-stopped
```

Cold, warm, partial, and stale states all follow the same rule: setup may converge the environment, but QA cannot start until a clean READY handoff exists. `auth_required` requires manual headed login; `unavailable` and `error` remain setup blockers.

## URL and environment

- Preserve the exact Designer URL, including `pageId`, `simulateRole`, host, and port. Campaign flows often use `?simulateRole=marketer&pageId=<page-id>`.
- Use Chrome for Testing's native user agent for Designer URLs. Intentional headless runs report `HeadlessChrome`; do not spoof a headed user agent unless a separately reproduced environment constraint proves it necessary. A non-Chromium automation identity can receive only the small open-graph shell.
- For `*.wfdev.io:8443`, use `--ignore-https-errors` when local TLS requires it.
- Pass every expected listener and endpoint explicitly to `scripts/designer-session.py`, then run its preflight before changing selectors. An empty shell, `502`, `504`, login redirect, or missing extension server is an environment or authentication signal until proven otherwise.
- For a local published `*.dev.webflowtest.io` page returning `500`, run `scripts/published-site-preflight.py <url>`. A `renderer_unavailable` result means the page needs the existing HUD `renderer` task on port `4040`; start that task, or run `ops/start_render_dev.sh` from the Webflow checkout, before debugging product code.
- Do not wait for `networkidle`; Designer and extensions maintain background traffic.

## Readiness and surfaces

The generic Designer readiness selector is:

```text
[data-automation-id="left-sidebar-component-browser-button"]
```

Useful Component Browser selectors:

- `[data-automation-id="component-browser"]`
- `[data-automation-id="component-group-preview"]`
- `[data-automation-id="component-thumbnail-surface-iframe"]`
- `[data-automation-id="component-thumbnail-surface-slot"]`
- `[data-automation-id="left-sidebar-campaign-overview-button"]`

Wait for the shell selector, then scope snapshots to the surface under test. When the selector visible in DevTools is absent from the main frame, enumerate frames and inspect the matching frame instead of weakening the selector.

## Canvas and frame selection

- The canvas commonly renders in an iframe such as `/site/empty.html`; the parent owns panels, chrome, overlays, and selection UI.
- Designer can expose the same canvas through multiple frames. Choose one canonical frame by URL, geometry, and target signal, or deduplicate by a semantic signature.
- For extension work, identify the iframe by expected origin and route, switch to it, wait for an extension-owned selector, and take a new snapshot before using refs.
- Capture parent Designer evidence for placement and chrome state, then extension or canvas evidence for the actual content.
- Transformed canvas element crops can be blank or dark even when the content is healthy. Prefer a viewport screenshot plus semantic canvas checks.

## Assertion order

1. Prove the expected environment, URL, tab, and frame.
2. Prove semantic state: visible counts, text, field names, roles, data attributes, component IDs, and selection state.
3. Prove the authorized interaction changed the expected scoped state with a snapshot diff.
4. Inspect a screenshot for layout, spacing, transformed content, or pixel-level output.
5. For published parity, verify the runtime script requests and semantic result before comparing visuals.

When repeated candidates exist, score them by target text, control count, data attributes, frame URL, and geometry. Do not use the first broad match as proof.

## Diagnostics

- `console` and `errors`: capture filtered failures after the surface is ready.
- `network requests --filter <value>` and request detail: prove the expected API, local SDK, loader, or bundle was requested.
- `network har start --content none`: prefer metadata-only capture. Never save bodies unless specifically authorized and reviewed for secrets and PII.
- `trace` and `profiler`: use for lifecycle or performance questions, and keep artifacts temporary.
- `eval`: return bounded, sanitized objects. Never return cookies, storage values, tokens, credentials, large DOM dumps, or full Designer API libraries.

## Safety and evidence

- Attached mode starts read-only unless the task authorizes a mutation. Reload, navigation, selection changes, canvas edits, undo, redo, publish, and app actions can change user state.
- The dedicated Chrome for Testing profile is the normal authenticated attached surface. A user-owned live tab is exceptional: obtain explicit authorization, require the user to pause interaction, and release it immediately after observing the unsaved state.
- Stateful connected-app actions can write site custom code, provider configuration, component definitions, and history. Establish the baseline and mutation boundary first.
- Keep screenshots, JSON, HAR, traces, and profiles in a temporary location outside the repository. Review screenshots and sanitize URLs before reporting them.
- Record semantic evidence before visual evidence, and state the ownership boundary, attached or isolated mode, headless or headed runtime mode, and verified cleanup result.
