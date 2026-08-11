---
name: tui-cli-design
description: Design or review keyboard-first terminal interfaces. Use for interactive CLIs, TUIs, searchable pickers, command palettes, configuration menus, prompts, terminal state machines, or bugs involving focus, Escape and back behavior, cancellation, re-entry, filtering, printable keys, custom keybindings, persistence, headless operation, or terminal accessibility.
---

# TUI and CLI Design

Treat an interactive terminal surface as a **visible state machine**, not a pile
of prompts. The user should always know where focus is, what Enter will do,
whether changes are saved, and how to go back without losing work.

## Workflow

1. **Classify the surface.** Name the interaction: one-shot command, prompt,
   list, searchable picker, command palette, configuration editor, dashboard,
   or long-running TUI. Establish whether input is interactive, piped, or
   headless. This step is complete when every supported mode has an explicit
   entry and exit contract.
2. **Inspect the native precedent.** Read the host framework's public component,
   focus, keybinding, rendering, and lifecycle APIs. Find the closest native
   interaction and copy its behavior before inventing another pattern. Reuse
   public components when possible; reproduce behavior rather than importing a
   private component. This step is complete when the implementation boundary
   and compatibility constraints are written down.
3. **Map the state machine.** List screens, focused control, mutable draft,
   committed state, transitions, validation errors, and terminal outcomes.
   Give one component or controller ownership of the complete lifecycle.
   This step is complete when every key transition has one destination and
   every terminal state resolves or closes exactly once.
4. **Write the interaction contract.** Assign navigation, activation, search,
   back, cancel, help, paging, and submit actions by semantic keybinding—not
   raw keys alone. Reserve printable input for text whenever an input is
   focused. This step is complete when a user can predict every visible key
   from the screen and footer.
5. **Shape the information hierarchy.** Put the common path first, show current
   and saved values, keep descriptions beside choices, and disclose advanced
   settings only after activation. Preserve a stable selection when a list
   grows or shrinks. This step is complete when the current location, current
   value, draft status, and next action are visible without documentation.
6. **Implement draft and cancellation semantics.** Configuration changes stay
   in memory until an explicit save. Escape moves back one level; Escape at the
   root either closes an unchanged draft or opens a discard decision. Show
   validation failures in place without closing. This step is complete when
   save, discard, cancel, and rejection paths preserve the promised state.
7. **Validate the interaction, not only the reducer.** Exercise the real custom
   component lifecycle, repeated open/close, focus restoration, filtering,
   empty results, custom keybindings, narrow widths, headless behavior, and
   persistence. Use [`references/test-matrix.md`](references/test-matrix.md)
   and account for every applicable row.
8. **Review the rendered experience.** Render representative screens at narrow
   and normal widths, then run the checklist in
   [`references/review-checklist.md`](references/review-checklist.md). The work
   is complete only when the implementation, tests, help text, and visible
   hints describe the same contract.

## Core contracts

- **One focus owner.** A custom flow owns its child screens in place. A nested
  dialog is safe only when the host API explicitly guarantees suspend, resume,
  focus restoration, and promise completion.
- **Text owns printable keys.** Letters, numbers, punctuation, paste, and IME
  input remain text while a field is focused. Never make `q`, `x`, or `exit` a
  hidden global escape hatch in a typing surface.
- **Escape follows the hierarchy.** Search or child screen → parent screen;
  root with clean draft → close; root with dirty draft → discard decision.
  Ctrl+C remains the application-level interrupt when the host defines it.
- **Activation is semantic.** Honor both list-confirm and input-submit bindings
  when an input and list share the screen. Wire the input's submit callback too.
- **Selection is an invariant.** After filtering or mutation, the selected
  index points to a visible row or to no row. Preserve the selected item's
  identity when catalogs refresh; otherwise clamp deliberately.
- **Search favors canonical identity.** Index the terms users actually type.
  Put canonical provider/item identities ahead of proxy or alias forms. Show a
  clear empty state and keep typing enabled.
- **State is truthful.** Distinguish saved, current, selected, staged, disabled,
  loading, refreshed, validation-error, and empty states visually and in text.
- **Rendering is bounded.** Every rendered line fits the supplied width; wrap
  prose and truncate identifiers deliberately. Propagate focus into embedded
  inputs when the framework requires it for cursor or IME positioning.
- **Headless is explicit.** Interactive prompts run only on a TTY. Automation
  gets flags or scriptable subcommands with deterministic output and exit
  codes, not a simulated keystroke session.

## References

- Read [`references/examples.md`](references/examples.md) when implementing a
  picker, configuration editor, focus lifecycle, or scriptable fallback.
- Read [`references/test-matrix.md`](references/test-matrix.md) before writing
  interaction tests.
- Read [`references/review-checklist.md`](references/review-checklist.md) for a
  design or code review.
- Read [`references/research.md`](references/research.md) when a design decision
  needs rationale or a primary source.
