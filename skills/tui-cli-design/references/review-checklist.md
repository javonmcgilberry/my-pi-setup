# TUI and CLI review checklist

## Information architecture

- Is the common path first and the advanced path progressively disclosed?
- Can the user see location, current value, saved value, and unsaved status?
- Are labels plain language, with descriptions next to unfamiliar choices?
- Does the review screen include every material setting without hiding custom details?

## Focus and lifecycle

- Is there one explicit focus owner for the active interaction?
- Are nested prompts or overlays supported by a documented suspend/resume contract?
- Does every close path resolve once, clean up resources, and restore host focus?
- Can the command reopen immediately after Escape, cancel, save, and validation failure?

## Keyboard contract

- Are navigation and activation semantic keybindings rather than raw-key assumptions?
- Do printable keys remain text whenever input is focused?
- Are Arrow keys, paging, Enter, Escape, help, and Ctrl+C behavior predictable?
- Are custom submit bindings honored by both the input and enclosing list?
- Do visible hints describe the bindings that actually work?

## Search and dynamic lists

- Does search index canonical identities and terms users actually type?
- Is the current item prioritized and visibly marked?
- Do query, selection, and viewport survive refreshes and list mutations?
- Is the empty state useful and non-terminal?
- Is refresh bounded, cancelable, and honest about cached or partial results?

## State and persistence

- Are saved and draft state separate?
- Are save and discard explicit, with in-place validation failures?
- Does cancellation preserve the documented state at every depth?
- Do interactive and headless commands share validation and persistence logic?

## Rendering and accessibility

- Does every line fit the supplied width at narrow and normal terminal sizes?
- Are focus, selection, current, disabled, loading, and error states meaningful without color alone?
- Does an embedded input receive focus propagation for cursor and IME support?
- Are motion, polling, and background updates bounded and non-disruptive?

## Evidence

- Are pure transitions and the real host lifecycle both tested?
- Does the suite cover repeated re-entry, literal `exit`, custom keybindings,
  empty results, list shortening, save rejection, discard, persistence, and headless behavior?
- Were representative screens rendered and reviewed rather than inferred from code?
- Were all duplicate interaction call sites and raw-key patterns searched before completion?
