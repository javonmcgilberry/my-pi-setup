# Connected-app workflows

Read the [`README`](../README.md) for the browser lifecycle. Use this reference
only when a Designer extension reads or changes connected application state,
provider configuration, component definitions, or site authorization.

## Confirm the running app

- Identify the extension client origin and API origin from the current
  environment. Do not assume a port or substitute a nearby development server.
- Confirm that the iframe URL belongs to the extension client rather than a CDN
  or package server.
- Inspect frame URLs and an extension-owned readiness selector before debugging
  application behavior.
- Treat an iframe on a sign-in route, a missing API server, and a failed provider
  request as separate findings.
- Keep provider credentials, OAuth tokens, Designer session tokens, and local
  bootstrap tokens out of commands, URLs, snapshots, reports, and screenshots.

## Keep state sources separate

Use the rendered canvas, extension UI, and Designer API model as separate
evidence sources. For component and slot work, record only the values needed to
identify the current state:

- selected element type
- component definition ID
- selected slot ID and slot name
- child count
- provider or layout name without customer data

Match a component instance through its component definition rather than
guessing a definition ID from an element instance ID. A canvas DOM probe can
miss provider markers while the API model and visible canvas remain correct.

## Handle mutations

Treat insertion, provider configuration, layout replacement, app connections,
undo, redo, reload, and publish as separate mutations unless the product
provides a transaction.

1. Capture a small baseline and an unrelated-content signature.
2. Perform only the authorized mutation.
3. Stop if unrelated state changes.
4. Verify the extension result and the canvas or model result separately.
5. For published behavior, prove the expected runtime request as well.

Bound undo and redo by the scenario's mutation count. Do not continue until an
unrelated history entry is reached. A development refresh can reset in-memory
provider authentication, so it is not persistence proof by itself.

Provider discovery, component registration, and Designer insertion can fail at
different layers. Classify the failing layer before changing application code.
Prefer normal app interaction or in-app history navigation over deep navigation
inside an extension iframe when the app uses a client-side router.

## Authorize one exact site

Select a site by its expected site ID, never by display name or result position.
Capture each visible authorization page as a sanitized file-backed surface,
then run:

```sh
python3 scripts/guarded-site-authorization.py \
  /tmp/sanitized-authorization-surface.json \
  --expected-site-id synthetic-site-id
```

Use the helper without mutation flags to check pagination and identify one
exact match. Add `--allow-selection` only after the baseline is captured and
provide the post-selection surface. Add `--allow-authorization` only for the
final authorized action and provide callback state containing `site_id` only.
Never pass a complete callback URL or authorization code.

The minimum sanitized shape is:

```json
{
  "pages": [
    {
      "checkboxes": [
        {"value": "synthetic-site-id", "checked": false}
      ],
      "has_next": false
    }
  ],
  "post_selection": null,
  "callback_state": null
}
```

OAuth can be valid for a cloud site while a local clone has a different site
ID. Keep signed identity checks intact and never rewrite auth data to force a
local authorization through.

## Evidence

Record only scenario-relevant, sanitized values:

- extension origin and route
- selected element and component definition IDs
- slot ID and child count
- provider or layout name without credentials or customer data
- before and after state IDs
- filtered request paths and statuses
- bounded undo and redo transitions
- inspected screenshots at user-visible checkpoints

If attached and isolated runs disagree, report state drift. An authorized live
tab is authoritative only for its unsaved collaborative state while the user
has paused interaction; the isolated run remains the repeatability check.
