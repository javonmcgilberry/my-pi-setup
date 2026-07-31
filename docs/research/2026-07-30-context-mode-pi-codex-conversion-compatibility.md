# Context Mode and Pi Codex Conversion Compatibility

## Question

How well do Context Mode's `ctx_*` commands work alongside `@howaboua/pi-codex-conversion`, particularly when the conversion extension exposes its Code Mode `exec` tool?

## Conclusion

The extensions coexist, but they are not integrated. Context Mode's tools remain available and provide their normal sandboxing, indexing, and output-reduction behavior when invoked directly. Pi Codex Conversion does not automatically route its Code Mode `exec` operations through Context Mode, so Context Mode cannot enforce or richly attribute those nested operations.

This matches the conclusion reached in Pi session `019fb1c7-52b7-7a7e-a149-1d833a756342`. Context Mode remains at version `1.0.169`; Pi Codex Conversion has moved from `3.0.2` to `3.0.5`, but its intervening changes did not add Context Mode integration.

## Current behavior

| Behavior | Status |
| --- | --- |
| Direct `ctx_*` tools are available beside Pi Codex Conversion | Yes |
| Direct `ctx_*` calls retain Context Mode's output-reduction behavior | Yes |
| Pi Codex Conversion automatically routes Code Mode `exec` through Context Mode | No |
| Context Mode's pre-call `bash` routing rule sees Code Mode `exec` | No |
| Context Mode richly attributes the outer Code Mode `exec` lifecycle event | No, it falls back to generic Pi attribution |
| Structured `exec_command` results can be normalized as Bash | Yes |
| Context Mode's displayed dollar estimate is provider-accurate Codex billing | No |

## Evidence

Pi Codex Conversion registers top-level `exec` and `wait` tools. Its Code Mode host invokes a fixed collection of nested tools directly, including `exec_command`, without emitting an ordinary Pi lifecycle event for every nested operation. Arbitrary external Pi tools such as Context Mode's `ctx_execute` are not inserted into that nested tool collection.

Context Mode's Pi adapter only applies its pre-call routing enforcement when the observed tool name is `bash`. Its result adapter has mappings for ordinary Pi tools and a generic fallback for unknown tools. The session extractor now normalizes `exec_command` to Bash, which improves structured-mode result classification, but it does not normalize the top-level Code Mode tool named `exec`.

The original session measured the practical consequence. Code Mode `exec` represented roughly 43 percent of the observed tool-output bytes in that run, while Context Mode could only report savings for operations that went through its own tools. Printing an entire `FILE_CONTENT` value from `ctx_execute_file` also negated much of its intended benefit because the model still received the full content.

## Recommendation

Keep both extensions. Use `ctx_*` deliberately for large file reads, command output, logs, and web content, and return only the compact answer needed from Context Mode's sandbox. Treat Code Mode `exec` traffic as outside Context Mode's routing and savings accounting until an explicit public integration is added.

A robust integration would require Pi Codex Conversion to expose nested execution through a public observable boundary, or Context Mode and Pi Codex Conversion to agree on a public routing and attribution contract. Patching either installed package would be the wrong boundary.

## Sources

- Original Pi session: `/Users/javonmcgilberry/.pi/agent/sessions/--Users-javonmcgilberry-.pi-pi-prework--/2026-07-30T06-47-37-911Z_019fb1c7-52b7-7a7e-a149-1d833a756342.jsonl`
- Context Mode Pi adapter: `/Users/javonmcgilberry/.pi/agent/npm/node_modules/context-mode/build/adapters/pi/extension.js`
- Context Mode session extractor: `/Users/javonmcgilberry/.pi/agent/npm/node_modules/context-mode/build/session/extract.js`
- Pi Codex Conversion Code Mode sources: `/Users/javonmcgilberry/.pi/agent/npm/node_modules/@howaboua/pi-codex-conversion/src/tools/code-mode/`
- [Context Mode repository](https://github.com/mksglu/context-mode)
- [Context Mode README](https://github.com/mksglu/context-mode/blob/main/README.md)
- [Pi Codex Conversion source](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-codex-conversion)
