# Research and native precedents

Use these sources for rationale, then verify the framework and product in front
of you. Web accessibility patterns do not map one-to-one onto a terminal, but
their focus, composite-widget, and predictable-keyboard principles transfer.

## Primary guidance

- [WAI-ARIA APG: Developing a Keyboard Interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)
  distinguishes movement between composite widgets from navigation within one,
  keeps focus visible, and calls for predictable key assignments.
- [WAI-ARIA APG: Listbox Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/listbox/)
  provides a reference interaction model for selection, arrow navigation, and
  type-ahead behavior.
- [Microsoft: Keyboard interactions](https://learn.microsoft.com/en-us/windows/apps/design/input/keyboard-interactions)
  emphasizes complete keyboard access, visible focus, conventional activation,
  and avoiding collisions between text entry and commands.
- [GNOME HIG: Keyboard](https://developer.gnome.org/hig/guidelines/keyboard.html)
  recommends logical focus order, full keyboard reachability, and platform
  conventions rather than application-specific surprises.
- [GNOME HIG: Search](https://developer.gnome.org/hig/patterns/nav/search.html)
  treats search as immediate filtering with a clear mode, result feedback, and
  an easy route back.
- [Command Line Interface Guidelines](https://clig.dev/) recommends prompts
  only for interactive terminals, actionable errors for automation, familiar
  interruption behavior, and output designed for both people and scripts.
- [fzf](https://github.com/junegunn/fzf) is a mature terminal precedent for
  type-to-filter selection, stable list navigation, composable input/output,
  and programmable keybindings.

## Pi precedents

For Pi work, inspect the active checkout rather than importing internals:

- `packages/coding-agent/src/modes/interactive/components/model-selector.ts`
  renders a current snapshot immediately, refreshes catalogs in the background
  with a timeout, preserves search, supports semantic keybindings, and owns its
  cleanup.
- `packages/coding-agent/src/modes/interactive/model-search.ts` orders search
  text as `provider`, `provider/id`, then provider-prefixed bare ID and name so
  canonical provider queries outrank proxy-provider IDs.
- `packages/tui/README.md` documents differential rendering, overlays, width
  limits, focus ownership, and focus propagation from a container into an
  embedded input for cursor and IME positioning.

Read those files from the Pi source checkout when behavior depends on the
current runtime. Copy public behavior and contracts; avoid private imports.

## Lessons captured from the Prewalk configuration redesign

- A nested `select` or `input` inside an extension custom component can restore
  the host editor while leaving the outer promise unresolved. Keeping child
  screens inside one component fixed Escape and immediate re-entry.
- A paginated prompt chain is not a searchable picker. The replacement needed
  live fuzzy filtering, a bounded viewport, current-state markers, canonical
  ranking, paging, and one back path.
- Raw printable exit shortcuts made ordinary search text unsafe. Semantic
  cancel bindings and hierarchy-based Escape removed the collision.
- Turning off a custom policy shortened its menu and invalidated the numeric
  selection. Restoring focus by row identity kept the activated action stable.
- Handling only list confirmation missed custom input-submit bindings. The
  enclosing component and input callback must agree on activation.
- Reducer tests did not prove the original lifecycle bug. Repeated real
  open/Escape/reopen tests were necessary.
- A stock child-process test inherited outer `PI_SUBAGENT_*` depth and budget
  state when run by a reviewer child. Isolating and restoring the namespace made
  the supposedly top-level fixture hermetic.
