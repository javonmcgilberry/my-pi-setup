# Connected App Workflows

Load this reference only for Campaign, Marketo, HubSpot, or another Designer extension that reads or mutates connected-app state.

## Environment and iframe checks

- Confirm both the extension client and app server ports. A visible iframe can still be on a sign-in route because its API server is absent.
- Confirm the iframe URL is the extension client rather than an adjacent CDN or package server.
- For local Marketo, the expected client is commonly `http://localhost:1337`; a fallback to `1338` can break origin-sensitive auth. The API may run on a separate port such as `3002`, and a CDN development server may use `127.0.0.1:5173`.
- Inspect frame URLs and the extension-owned readiness selector before diagnosing the application.
- Do not print or place provider credentials, OAuth tokens, Designer session tokens, or local bootstrap tokens in commands, snapshots, reports, URLs, or screenshots.

## Model and canvas state

- Keep the rendered canvas DOM, extension list, and Designer API model as separate evidence sources.
- Match current-page component instances through `ComponentInstance.getComponent().id`. Do not infer the definition ID from the shape of an element instance ID.
- For slot-sensitive insertion, capture the selected element, selected slot, slot IDs, display names, and child counts before and after the action.
- `selectedSlotId` can be the slot definition ID string while `getSlots()` returns structured IDs. Compare it with the structured slot's `slot` field.
- A canvas DOM probe can miss provider markers while the Designer API and visible canvas remain correct. Pair a bounded API snapshot with the Designer viewport.

Use `eval` only inside the confirmed extension iframe and return filtered values. Never dump the complete Designer model when a small set of IDs, types, names, and counts answers the question.

## Stateful actions

- Treat insertion, provider configuration, layout replacement, app connections, undo, redo, reload, and publish as separate mutations unless the product explicitly provides a transaction.
- Capture a small baseline and an unrelated-content signature before mutation. Stop immediately if unrelated state changes.
- Bound undo and redo by the mutation count from the scenario. Never continue until Undo becomes disabled because that can cross into unrelated site history.
- After a connected-app action, verify the extension result and canvas or model result separately. For published behavior, also prove the expected runtime script request after publish or local routing.
- Do not use the Designer development refresh button as the only persistence proof; it reloads the iframe and can reset in-memory provider authentication.

## Exact-site authorization

- Select a Webflow site by its expected site ID, never by display name or result position.
- Capture each visible authorization page as a sanitized file-backed surface. Run `scripts/guarded-site-authorization.py` without mutation flags to verify pagination and one exact match.
- Use agent-browser for the actual pagination and checkbox actions. Add `--allow-selection` only after the baseline is captured, then provide the post-selection surface so the helper can verify that one checkbox is selected and the authorization action is enabled.
- Add `--allow-authorization` only when the final action is authorized. Provide parsed callback state containing only `site_id`; never provide a complete callback URL or authorization code.

The initial surface shape is:

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

## Marketo and HubSpot cautions

- Marketo provider discovery can fail because a selected provider form itself does not render. Separate provider-data failure from component registration or Designer insertion failure.
- Marketo TanStack Router base paths can break after direct frame navigation. Prefer normal app interaction or in-app history navigation over navigating the iframe to a deep path.
- Duplicate provider form names require scoping to the intended list, row, component definition, and current frame.
- HubSpot or Marketo OAuth can be valid for a cloud site while a local clone has a different site ID. Do not rewrite signed identity data or weaken product checks to force authorization.
- Shared authenticated provider sessions are sensitive. Do not export, persist, or route their tokens unless the user explicitly authorizes the exact bounded workflow.

## Evidence

Record only sanitized, scenario-relevant values:

- extension frame origin and route
- selected element type, component definition ID, slot ID, and child count
- provider form or layout name without credentials or customer data
- before and after component or state IDs
- filtered request paths and statuses
- bounded undo and redo transitions
- inspected screenshots at user-visible checkpoints

If attached and isolated sessions disagree, report the state-drift finding. The agent-owned dedicated profile is the normal attached surface. An explicitly authorized user-owned live tab is authoritative only for its unsaved collaborative state while the user has paused interaction; release it immediately afterward. The isolated run remains the repeatability check.
