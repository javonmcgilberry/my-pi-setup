# Pi Intercom and Compound Engineering update review

Date: 2026-07-30

## Verdict

Update `pi-intercom`. Version 0.9.1 fixes cross-project queued-mail misrouting that is directly relevant when several same-named Pi sessions are running across repositories. It also improves local-socket and renderer performance without changing tool schemas or normal send, ask, and reply behavior. The [official v0.9.1 release](https://github.com/nicobailon/pi-intercom/releases/tag/v0.9.1) describes the routing and performance changes, and the [v0.9.0 to v0.9.1 comparison](https://github.com/nicobailon/pi-intercom/compare/v0.9.0...v0.9.1) bounds the update.

The Compound Engineering update is also reasonable, but it is narrower and less urgent. It advances the installed Git checkout by one commit and only changes cross-model peer supervision for `ce-code-review`, `ce-doc-review`, and `ce-pov`. It does not change Prewalk, pi-subagents coordination, planner or executor model policy, `ce-plan`, or `ce-work` orchestration directly. The complete [installed-to-current comparison](https://github.com/EveryInc/compound-engineering-plugin/compare/9e8d4a4846554892dcf1db8a18aeb822d89d898b...bfccada9520b7d7532b69d71d61f9996c30a6b29) contains one commit and twelve changed files.

No package was updated during this research.

## Installed and available state

| Package | Installed evidence | Available state | Assessment |
|---|---|---|---|
| `pi-intercom` | `~/.pi/agent/npm/node_modules/pi-intercom/package.json` and `package-lock.json` resolve 0.9.0, matching the [official 0.9.0 package source](https://github.com/nicobailon/pi-intercom/blob/v0.9.0/package.json). | 0.9.1, published in the [official release](https://github.com/nicobailon/pi-intercom/releases/tag/v0.9.1). | Small safety and performance update. |
| `github.com/EveryInc/compound-engineering-plugin` | Git checkout is commit [`9e8d4a48`](https://github.com/EveryInc/compound-engineering-plugin/commit/9e8d4a4846554892dcf1db8a18aeb822d89d898b); its package metadata reports 3.20.0. | Git main is commit [`bfccada9`](https://github.com/EveryInc/compound-engineering-plugin/commit/bfccada9520b7d7532b69d71d61f9996c30a6b29); its [package metadata](https://github.com/EveryInc/compound-engineering-plugin/blob/bfccada9520b7d7532b69d71d61f9996c30a6b29/package.json) still reports 3.20.0. | A Git revision update, not a semantic-version bump. |

## pi-intercom 0.9.1

### What matters here

Version 0.9.0 could redeliver queued mail, including a reply originally addressed to an exact disconnected session ID, to an unrelated live session with the same name in another project. Version 0.9.1 requires the normalized working directory to match for name-based mailbox identity, so multi-repository sessions no longer collide through a shared name alone. The [routing fix commit](https://github.com/nicobailon/pi-intercom/commit/d7691b6ff07410e6942404a8b20d9ab9e1b6b913) contains the implementation and regression tests.

The update also replaces repeated fragmented-frame concatenation with a bounded state-machine reader and single-allocation writes, and it caches inline preview and wrapped-body rendering. The maintainers report up to roughly 28x faster heavily fragmented frame handling and roughly 2x to 3x faster repeated long-message rendering in the [official release notes](https://github.com/nicobailon/pi-intercom/releases/tag/v0.9.1); the [performance commit](https://github.com/nicobailon/pi-intercom/commit/c44c135f981d65ced1c66eed40f7c221be99d6d2) contains the source and tests.

The [complete version comparison](https://github.com/nicobailon/pi-intercom/compare/v0.9.0...v0.9.1) shows no changes to tool schemas, event contracts, subagent bridge metadata, normal ask/reply semantics, dependencies, or configuration schema. No migration is documented.

### Operational note

The mailbox routing fix is implemented in the broker, so an already-running 0.9.0 broker retains the old behavior until it exits. After updating, restart or cycle all Pi sessions before relying on the fix. This follows from the broker-side changes in the [routing commit](https://github.com/nicobailon/pi-intercom/commit/d7691b6ff07410e6942404a8b20d9ab9e1b6b913).

## Compound Engineering plugin

### What changed

The only available commit is [`fix(cross-model): idle-detect streaming peer routes`](https://github.com/EveryInc/compound-engineering-plugin/pull/1287). Claude and Cursor-family peer routes now use `stream-json`, and their runners watch peer-log growth so stalled peers can be reaped by an idle deadline instead of consuming the complete hard deadline. Grok CLI remains on buffered JSON and a hard deadline because its schema and streaming modes cannot be combined. The [merged pull request](https://github.com/EveryInc/compound-engineering-plugin/pull/1287) documents the design, tests, and residual limitation.

This affects only the cross-model scripts and references owned by `ce-code-review`, `ce-doc-review`, and `ce-pov`, plus their tests and solution notes. The [official comparison](https://github.com/EveryInc/compound-engineering-plugin/compare/9e8d4a4846554892dcf1db8a18aeb822d89d898b...bfccada9520b7d7532b69d71d61f9996c30a6b29) contains no changes to Prewalk, pi-subagents, the Pi extension entry point, analytics, `ce-plan`, or `ce-work`.

Model choices and reasoning levels are unchanged. The adapters change their output transport and liveness supervision, while retaining the existing model arguments and read-only permissions in the [cross-model review implementation](https://github.com/EveryInc/compound-engineering-plugin/blob/bfccada9520b7d7532b69d71d61f9996c30a6b29/skills/ce-code-review/scripts/cross-model-adversarial-review.sh).

### Cost and reliability implications

The change should reduce wasted time and spend when a streaming peer wedges because the runner can terminate it after the peer log stops growing. It does not add usage or cost analytics and does not change Prewalk receipts or pi-subagents lineage. These boundaries are visible in the [complete comparison](https://github.com/EveryInc/compound-engineering-plugin/compare/9e8d4a4846554892dcf1db8a18aeb822d89d898b...bfccada9520b7d7532b69d71d61f9996c30a6b29).

Streaming output increases log volume. The upstream solution note says the outer peer runner kills a worker if `CE_PEER_LOG_MAX_BYTES`, currently 10 MB, is exceeded, so an unusually chatty review could trade a better liveness signal for a log-cap failure. The maintainers explicitly document that risk in the [buffering and progress-detection note](https://github.com/EveryInc/compound-engineering-plugin/blob/bfccada9520b7d7532b69d71d61f9996c30a6b29/docs/solutions/skill-design/cli-output-buffering-for-progress-detection.md).

Upstream quiet-interval measurements used Claude Code 2.1.220 and Cursor Agent 2026.07.23, while this machine currently reports Claude Code 2.1.218 and Cursor Agent 2026.05.01. Both installed CLIs expose the required `stream-json` option, but their exact quiet intervals were not measured here. The upstream default remains 480 seconds, well above its largest reported streaming-route quiet interval of 47 seconds; the versions, measurements, and chosen floor are recorded in the [official quiet-interval note](https://github.com/EveryInc/compound-engineering-plugin/blob/bfccada9520b7d7532b69d71d61f9996c30a6b29/docs/solutions/skill-design/quiet-interval-floors-for-streaming-peer-routes.md).

### Compatibility

No migration or package-version change is present. The update changes supervision only when the affected cross-model review routes run, so ordinary planning, plan execution, Prewalk epochs, and pi-subagents launches keep their current contracts. The [one-commit comparison](https://github.com/EveryInc/compound-engineering-plugin/compare/9e8d4a4846554892dcf1db8a18aeb822d89d898b...bfccada9520b7d7532b69d71d61f9996c30a6b29) is the authoritative scope.

## Recommendation

1. Update `pi-intercom`, then restart all Pi sessions so the corrected broker takes ownership.
2. Update Compound Engineering if cross-model CE review is in use. The change is a focused reliability improvement, but the immediate Prewalk and pi-subagents work does not depend on it.
3. Do not combine either update with changes to the locally developed Prewalk or canonical pi-subagents repositories. These package revisions do not replace or alter the model-policy and analytics contracts implemented there.
