# Context Mode and Code Mode integration options

Date: 2026-07-30

## Verdict

There is a worthwhile improvement path, but it should be split into two pieces.
Context Mode can improve accounting today by reading the nested traces that Pi
Codex Conversion already publishes in the public top-level `exec` and `wait`
results. Reliable pre-execution routing needs an explicit public contract from
Pi Codex Conversion because Pi does not expose a public API for invoking another
registered tool or lifecycle events for work performed inside a custom tool.

Do not patch either installed package. Make the changes upstream in Context Mode
and Pi Codex Conversion, with a small versioned composition contract between
them.

## Ranked options

### 1. Teach Context Mode to consume Code Mode traces

**Value: high. Complexity: low to medium. Recommended first.**

Pi Codex Conversion already returns `details.codeMode`, `details.cellId`, and
bounded `details.traces` on the public `tool_result` for `exec` and `wait`.
Every trace carries its nested tool name, input, status, and bounded result.
Context Mode currently ignores those details and records the outer `exec` as a
generic Pi event.

Context Mode should recognize the Code Mode result envelope, correlate yielded
cells by `cellId`, deduplicate traces by trace ID, and pass completed nested
`exec_command`, `apply_patch`, and other recognized traces through its existing
event extractor. The outer `exec` can remain as one container event while
semantic events come from the nested traces. `droppedTraceCount` must make
coverage explicitly incomplete instead of pretending the trace list is
exhaustive.

This improves session history, active memory, and usage attribution without a
new Pi API. Prewalk already demonstrates the same public trace-consumption
pattern in `prewalk/src/mutation.ts`.

Sources:

- [Pi Codex Conversion Code Mode result envelope](https://github.com/IgorWarzocha/howaboua-pi-stuff/blob/main/packages/pi-codex-conversion/src/tools/code-mode/tool-result.ts)
- [Pi Codex Conversion bounded trace store](https://github.com/IgorWarzocha/howaboua-pi-stuff/blob/main/packages/pi-codex-conversion/src/tools/code-mode/trace-store.ts)
- [Context Mode Pi `tool_result` handling](https://github.com/mksglu/context-mode/blob/main/src/adapters/pi/extension.ts)
- Local precedent: `prewalk/src/mutation.ts`

### 2. Tighten the routing instruction for immediate savings

**Value: medium. Complexity: very low. Available now.**

Context Mode already injects a short hierarchy telling the model when to use
`ctx_batch_execute`, `ctx_execute`, and `ctx_execute_file`. It should explicitly
cover Code Mode: use direct top-level `ctx_*` tools for large reads, logs,
multi-command research, and web payloads; use Code Mode `exec_command` for
small bounded shell results and mutation workflows.

The project `AGENTS.md` can carry the same compact rule immediately. This will
improve compliance, but it is instruction-level guidance and cannot enforce the
choice. It also needs to warn against printing an entire `FILE_CONTENT` value
from the sandbox, since doing that returns the payload to model context and
removes the saving.

Source:

- [Context Mode Pi routing anchor](https://github.com/mksglu/context-mode/blob/main/src/adapters/pi/extension.ts)
- [Context Mode Pi instruction file](https://github.com/mksglu/context-mode/blob/main/configs/pi/AGENTS.md)

### 3. Publish an opt-in Code Mode tool-provider contract

**Value: high. Complexity: medium to high. Recommended long-term enforcement boundary.**

Pi Codex Conversion internally supports multiple Code Mode tool providers
through `registerCodeModeTools()` and a process-scoped shared runtime. This is
the right architectural seam, but it is not documented or exported as a stable
package API. Depending on its `dist/` or `src/` path would be a private runtime
import.

Pi Codex Conversion should expose a stable public entry point that lets another
extension register selected programmatic Code Mode tools. Context Mode could
then register Code Mode-native `ctx_*` wrappers using its existing bridge
client. The contract should be opt-in and selective because interactive Pi
tools and tools requiring host UI do not belong inside the isolated Code Mode
runtime.

This produces actual routing inside `exec`, preserves Context Mode's own
sandbox and accounting path, and avoids trying to reconstruct JavaScript source
from the outer `exec` call.

Sources:

- [Internal provider registration](https://github.com/IgorWarzocha/howaboua-pi-stuff/blob/main/packages/pi-codex-conversion/src/tools/code-mode/tools.ts)
- [Code Mode provider collection](https://github.com/IgorWarzocha/howaboua-pi-stuff/blob/main/packages/pi-codex-conversion/src/tools/code-mode/shared-runtime.ts)
- [Context Mode Pi MCP bridge](https://github.com/mksglu/context-mode/blob/main/src/adapters/pi/mcp-bridge.ts)

### 4. Add a versioned nested-lifecycle contract if generic enforcement is needed

**Value: medium. Complexity: high. Defer unless more extensions need it.**

Pi's public `tool_call` and `tool_result` events surround top-level Pi tool
execution. A custom tool that directly invokes its own nested implementation
does not automatically create another Pi lifecycle pair. Pi also does not
publish a supported method for looking up and invoking a registered tool by
name.

A generic before-nested-tool and after-nested-tool contract could let Context
Mode apply routing and accounting to Code Mode operations, but Pi Codex
Conversion would still need to emit or use that contract around its internal
calls. This is broader than the immediate problem, and option 1 already solves
accounting while option 3 provides a cleaner enforcement seam.

Source:

- [Pi extension API and lifecycle documentation](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
- [Pi Codex Conversion direct nested invocation](https://github.com/IgorWarzocha/howaboua-pi-stuff/blob/main/packages/pi-codex-conversion/src/adapter/code-mode/nested-tool-adapter.ts)

## Options to avoid

- Do not parse arbitrary `exec` JavaScript and block it based on string
  matching. Code can compute commands dynamically, so the result would be
  incomplete and fragile.
- Do not add a Code Mode TOML custom tool that launches a second Context Mode
  process. Custom tools are command-backed and cannot invoke the already
  registered Pi `ctx_*` tool, so this risks separate state and duplicate
  bridges.
- Do not disable Code Mode globally merely to improve Context Mode
  classification. Structured `exec_command` is easier for Context Mode to
  recognize, but losing Code Mode composition is a larger tradeoff than the
  accounting gap requires.
- Do not expose every registered Pi tool inside Code Mode. Some tools depend on
  Pi UI, lifecycle state, or interactive approval behavior that the isolated
  runtime cannot preserve.

## Recommended sequence

1. Add the compact Code Mode routing rule to the project instructions and
   Context Mode's Pi prompt.
2. Implement nested-trace extraction in Context Mode with fixtures for
   completed, failed, yielded, resumed, duplicated, and dropped traces.
3. Measure the resulting reduction and event coverage on representative Pi
   sessions.
4. If instruction compliance remains insufficient, upstream a documented,
   versioned Code Mode provider API and register selected `ctx_*` wrappers
   through it.

This sequence captures most of the immediate value without changing Pi core.
The provider API becomes necessary only when the requirement moves from better
guidance and accurate accounting to guaranteed routing inside Code Mode.
