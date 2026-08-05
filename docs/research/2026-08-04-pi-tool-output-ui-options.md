# Research: Pi tool-output presentation and Code Mode UI options

## Executive summary

Pi’s built-in control is global: `Ctrl+O` (`app.tools.expand`) toggles all tool output between collapsed and expanded states. There is no current per-tool-call collapse API, and ordinary settings do not control the visibility of Code Mode’s nested trace rows.

This repository already has the lowest-risk Code Mode settings: `compactTools: true` and `codeModeDetails: false`. The observed `• Ran / Explored` noise is produced by Code Mode’s renderer iterating nested traces, so changing those settings cannot remove it. The practical choices are: keep Code Mode and accept/locally alter trace rendering, or disable Code Mode (`beta.codeMode: false`) and use the structured adapter.

## Findings

1. **Pi’s built-in collapse control is global.**
   `app.tools.expand` defaults to `ctrl+o`; it collapses or expands tool output. Keybindings can be overridden in `~/.pi/agent/keybindings.json`, then reloaded with `/reload`. Older `expandTools` identifiers are migrated automatically. [Pi keybindings](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/keybindings.md)

2. **Pi exposes global expansion state, not per-call state.**
   Extensions can call `ctx.ui.getToolsExpanded()` and `ctx.ui.setToolsExpanded()`, but these affect the global transcript state. Current Pi has no `setToolExpanded(toolCallId, ...)`. Upstream issue #3114 explicitly identifies this limitation and proposes either a `collapsed` field on tool results, a per-call API, or a renderer-level signal. [Issue #3114](https://github.com/badlogic/pi-mono/issues/3114)

3. **Custom tool renderers are the supported presentation extension point.**
   `renderCall(args, theme, context)` controls the call row; `renderResult(result, { expanded, isPartial }, theme, context)` controls result output. Renderers can return an empty `Container` when collapsed, display summaries, and use `keyHint("app.tools.expand", ...)`. `renderShell: "self"` opts out of Pi’s default boxed shell. [Pi extensions](https://pi.dev/docs/latest/extensions) · [Pi TUI](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/tui.md)

4. **Overriding a built-in tool is possible but has compatibility cost.**
   Re-registering a built-in tool replaces it; execution must delegate to the original implementation. Pi resolves call and result renderers independently, so an override can retain built-in rendering by omitting one slot. Official examples demonstrate compact and minimal renderers for `read`, `bash`, `edit`, `write`, `grep`, `find`, and `ls`. [Official minimal-mode example](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/examples/extensions/minimal-mode.ts) · [Built-in renderer example](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/examples/extensions/built-in-tool-renderer.ts)

5. **Display collapsing does not reduce model-visible output.**
   Pi’s built-in tools truncate output at 2,000 lines or 50 KB, whichever comes first; bash preserves full truncated output in a temporary file. Renderer collapse only changes the TUI. [Tool truncation](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/truncation.md) · [Bash source](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/tools/bash.ts)

6. **The current Code Mode settings are already optimized for hiding outer detail.**
   `@howaboua/pi-codex-conversion` maps:
   - `ui.codeModeDetails` → rich outer `exec`/`wait` rendering and JavaScript/output detail.
   - `ui.compactTools` → compact nested tool output.
   - `ui.toolRenaming` → Codex-style nested labels.

   The current repository values are `codeModeDetails: false`, `compactTools: true`, and `toolRenaming: true`. [Codex settings source](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/ui/settings/config-items.ts) · [Codex config source](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/adapter/activation/config.ts)

7. **Why `• Ran / Explored` remains visible.**
   Code Mode’s renderer always calls `renderTraceAndOutput()` for recorded nested traces. Generic traces are rendered as `Running`, `Ran`, or `Failed`; programmatic nested tools may render their own Codex-style labels such as `Explored`. `codeModeDetails: false` suppresses the outer JavaScript/result body but does not suppress the trace list. Nested options also hard-code `showOutputWhenCollapsed: true`; `compactTools` changes detail formatting, not trace enumeration. [Code Mode rendering](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/tools/code-mode/rendering.ts) · [Code Mode registration](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/adapter/code-mode.ts)

8. **`toolRenaming: false` is not a noise fix.**
   It can replace polished labels with generic tool names, but the trace rows remain. `codeModeDetails: true` is counterproductive for this goal because it enables more outer Code Mode detail.

9. **The repository’s existing `pi-tool-renderer` is already compact for direct tools.**
   Current configuration is under `vstack.extensionManager.config["@vanillagreen/pi-tool-renderer"]`; its documented default-enabled renderer currently uses:
   - read: `summary`
   - search: `count`
   - bash: `opencode`
   - MCP: `summary`

   The package also supports hidden/summary/preview modes, line caps, delayed bash tails, generic external-tool renderers, optional `apply_patch` rendering, and optional rich edit/write diffs. It does not document control over Code Mode’s internal trace list. [pi-tool-renderer README](https://github.com/vanillagreencom/vstack/blob/main/pi-extensions/pi-tool-renderer/README.md)

10. **Likely renderer interaction with Code Mode.**
    `pi-tool-renderer` overrides ordinary registered tools and renders selected external/MCP tools. Code Mode traces are assembled inside `pi-codex-conversion`’s `renderCodeModeResult`, so they are not ordinary top-level Pi tool rows. Therefore, changing `pi-tool-renderer`’s read/search/bash modes is unlikely to remove nested Code Mode trace rows. Both packages can also register overlapping renderers for ordinary tools; load order and ownership settings matter.

11. **Relevant ecosystem options:**

    | Option | Strength | Limitation/conflict |
    |---|---|---|
    | Official `minimal-mode.ts` | Small, authoritative example; hides result bodies when collapsed while retaining calls | Overrides built-ins; does not address Code Mode’s internally rendered traces |
    | `@vanillagreen/pi-tool-renderer` | Already installed; broad direct-tool controls, generic/MCP renderers, bash tails, diff UI | No documented Code Mode trace control; ownership can conflict with other renderer packages |
    | [`pi-tool-display`](https://github.com/MasuRii/pi-tool-display) | OpenCode-style presets; `opencode` hides read/search output and keeps bash collapsed; custom-tool adapter API | Overrides the same built-ins/global UI; no evidence it controls Code Mode traces; conflicts with existing renderer unless ownership is disabled |
    | [`@vinyroli/pi-tool-codex`](https://github.com/vinyroli/pi-tool-codex) | Similar compact presets and diff presentation | Fork/rebrand with the same renderer ownership conflict; no Code Mode trace evidence |
    | [`pi-minimal-toolcall`](https://github.com/fahmiirsyadk/pi-minimal-toolcall) | Groups consecutive calls; controls default expansion and thinking label | Other extension renderers break grouping; custom non-built-in overrides await fuller SDK support |
    | [`pi-collapse-outputs`](https://www.npmjs.com/package/pi-collapse-outputs) | Simple one-line summaries for built-in tools | Another built-in renderer override; no Code Mode support evidence |
    | `tool_batch` in vstack renderer | Reduces repeated direct model calls to one summarized row | Changes the model-facing tool surface and is unsuitable for order-dependent, streaming, or mutating calls |

12. **Code Mode itself has hard limits relevant to presentation.**
    Current Code Mode exposes only `exec` and `wait` to the provider and composes shell, patch, image, web, and custom tools locally. The outer result contains nested trace metadata. Removing traces in a `tool_result` hook would modify the persisted/model-visible result, not merely the TUI, and risks losing diagnostic context. [Codex README](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/README.md)

## Recommendations

### Low-risk configuration

1. Keep `ui.codeModeDetails: false` and `ui.compactTools: true`; they are already the least noisy Code Mode configuration.
2. Keep `ui.toolRenaming: true` if semantic labels are preferred. Set it false only if generic names are less distracting; it will not reduce row count.
3. Use `Ctrl+O` for temporary global expansion. A personal `keybindings.json` can remap `app.tools.expand`; no tracked keybindings file currently exists.
4. Keep the existing `pi-tool-renderer` modes unless direct-tool output is still excessive. `readOutputMode: hidden` and `searchOutputMode: hidden` are reasonable direct-tool reductions, but will not affect Code Mode traces.
5. Disable Code Mode (`beta.codeMode: false`) only if eliminating the trace rows is more important than Code Mode’s composition model. This is a behavior/provider change, not a presentation-only change.

### Local extension

- A small renderer extension can compact ordinary built-in tools using the official `renderResult` API and preserve errors, counts, diffs, and `Ctrl+O` expansion.
- A true Code Mode fix requires changing or wrapping the Code Mode renderer itself so `renderTraceAndOutput()` supports `hidden`, `summary`, and `full` trace modes. A generic `tool_result` content rewrite is not recommended because it changes model-visible/session-persisted data.
- Avoid installing a second broad built-in renderer alongside `pi-tool-renderer` unless ownership is explicitly partitioned.

### Upstream feature request

Request two first-class features:

1. Pi: per-tool-call collapse metadata/API, following issue #3114, while keeping model result content separate from TUI state.
2. `pi-codex-conversion`: a `ui.codeModeTraceMode` setting (`hidden`, `summary`, `full`) or equivalent `showNestedTraces` option. Errors, yielded/background status, and counts should remain visible in summary mode; `Ctrl+O` should reveal full traces.

## Worktree note

The worktree was already dirty before this research. Pre-existing changes were:

`AGENTS.md`, `README.md`, `config/manifest.json`, `package-lock.json`, `package.json`, deletion of `pi-explore-subagents.json`, `prewalk`, `scripts/check.sh`, `scripts/drift.sh`, `settings.json`, `setup.sh`, and `sync`.

No source configuration was intentionally edited by this research.

## Sources

- [Pi keybindings](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/keybindings.md) — official collapse key and customization.
- [Pi extensions](https://pi.dev/docs/latest/extensions) — extension and renderer APIs.
- [Pi TUI](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/tui.md) — components and rendering contracts.
- [Pi issue #3114](https://github.com/badlogic/pi-mono/issues/3114) — missing per-call collapse API.
- [Codex rendering source](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/tools/code-mode/rendering.ts) — exact trace/output behavior.
- [Codex configuration source](https://cdn.jsdelivr.net/npm/@howaboua/pi-codex-conversion@3.0.7/src/adapter/activation/config.ts) — exact UI levers/defaults.
- [vstack pi-tool-renderer](https://github.com/vanillagreencom/vstack/blob/main/pi-extensions/pi-tool-renderer/README.md) — current installed renderer’s controls.
- [Pi official minimal-mode example](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/examples/extensions/minimal-mode.ts) — local renderer pattern.
- [pi-tool-display](https://github.com/MasuRii/pi-tool-display) — OpenCode-style ecosystem option.
- [pi-minimal-toolcall](https://github.com/fahmiirsyadk/pi-minimal-toolcall) — grouping/minimal ecosystem option.

## Gaps

No runtime screenshot or fresh interactive A/B test was available. Renderer load order and exact extension-manager defaults should be verified in a clean Pi session before adopting another renderer package.