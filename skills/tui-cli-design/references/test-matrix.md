# Interaction test matrix

Test the smallest pure transition helpers first, then the real component
lifecycle. Mark every applicable row pass, not-applicable, or blocked.

## State and rendering

- Initial screen, focused row, current value, and saved value are correct.
- Every screen renders within narrow and normal widths without overflowing.
- Long labels wrap or truncate deliberately; ANSI styling does not corrupt width.
- Empty, loading, refreshed, partial-error, validation-error, and disabled states are distinguishable.
- Help and footer hints match active bindings and available actions.

## Navigation and activation

- Up/Down move one row; Page Up/Page Down move by the documented viewport.
- Boundary behavior is intentional: wrap or stop, with tests for both ends.
- Enter activates the visible selected row exactly once.
- Custom list-confirm and input-submit bindings both activate correctly.
- List mutation and filtering keep the selected item visible or clamp safely.
- A shortened menu never strands focus on an unrelated `Back` or `Save` row.

## Text and search

- Every printable character remains text while input is focused, including
  `q`, `x`, the literal word `exit`, punctuation, and spaces.
- Backspace, paste, multi-byte text, and IME cursor placement follow the host API.
- Canonical provider/item queries outrank proxy-provider or alias matches.
- Filtering is live, case behavior is documented, and empty results still allow typing.
- Escape clears or leaves search according to the visible hierarchy; it never exits the host unexpectedly.
- Background refresh preserves the query and selected identity and has a bounded timeout.

## Lifecycle and focus

- Opening the component, escaping, and immediately reopening works repeatedly.
- Every save, cancel, and close path resolves its promise exactly once.
- The host editor or previous component regains focus after close.
- Child screens do not invoke an undocumented nested-dialog lifecycle.
- Resize, rerender, and async completion do not steal focus or resurrect a closed component.
- Closing aborts refreshes, timers, listeners, and other owned resources.

## Draft, save, and discard

- Changes remain draft-only until explicit save.
- Review shows every material value, including custom targets and fallbacks.
- Successful save persists once, updates the saved baseline, and closes as promised.
- Save rejection displays an in-place error, preserves the draft, and does not close.
- Escape on a clean root cancels; Escape on a dirty root opens discard confirmation.
- Escape from discard keeps editing; explicit discard restores the saved state.
- Help and child navigation preserve the draft.

## Headless and compatibility

- Non-TTY invocation uses flags/subcommands or returns an actionable error.
- Scriptable commands and the TUI call the same validation and persistence layer.
- Output and exit codes are deterministic enough for automation.
- Public host APIs are used; behaviorally reproduced native patterns have a test contract.
- Terminal capability differences, missing colors, and narrow screens retain meaning.
- Repeated invocations do not leak global environment, focus, or process state.

## Regression proof for lifecycle bugs

For a reported Escape or re-entry bug, include a test that:

1. Opens the real custom component through the host UI boundary.
2. Navigates into the affected child screen.
3. Escapes to the parent and closes.
4. Verifies the outer promise resolved and host focus returned.
5. Opens the command again in the same process.
6. Completes a save or cancel path successfully.

A reducer-only test is insufficient for a host focus or component replacement bug.
