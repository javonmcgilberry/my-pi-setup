<pi-intercom>
Coordinate with other local pi sessions on related codebases. Use `/skill:pi-intercom` for patterns.

**When:** Same codebase (parallel work), reference codebase (consulting patterns), related repos (shared libraries).

**Not when:** Unrelated codebases, trivial questions, or when you can proceed independently.

**Principle:** Prefer `send` for notifications; `ask` only when blocked waiting for input.
</pi-intercom>

<context-mode>
Use top-level `ctx_*` tools for large reads, logs, research, and web payloads.
Use Code Mode `exec_command` only for small bounded shell output and mutations.
Never print the full `FILE_CONTENT`; return only the answer needed.
</context-mode>

<worktree-dependencies>
Git worktrees do not automatically share installed dependencies. Before
installing again, point a worktree at the main checkout's dependencies:

\`\`\`sh
MAIN_CHECKOUT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
ln -s "$MAIN_CHECKOUT/node_modules" node_modules  # when node_modules is missing
export NODE_PATH="$MAIN_CHECKOUT/node_modules"
export PATH="$MAIN_CHECKOUT/node_modules/.bin:$PATH"
\`\`\`

The \`node_modules\` symlink is required for scripts that invoke
\`./node_modules/.bin/*\`; \`NODE_PATH\` alone is not sufficient. Do not share
dependencies when the worktree changes the dependency manifest or lockfile
unless the main checkout has already installed the matching dependency graph.
</worktree-dependencies>

<pi-subagents>
Use Pi subagents with mutation-safe orchestration.

**Mutation-capable children:**
- Never pass `turnBudget` or `toolBudget` to an implementation worker, fix worker, edit-authorized reviewer, or any other child that may mutate files. Do not work around this rule by raising count caps: assistant-turn and tool-call counts do not measure delivery safety.
- Give one writer one narrow, serial milestone in a cwd/worktree. Do not run concurrent writers against the same worktree.
- Use an elapsed `timeoutMs`/`maxRuntimeMs` only with enough margin. A timeout is not a mutation-safe boundary. When a checkpoint is needed, request it before the deadline and tell the child to emit it after the current tool returns, including changed files, build/test state, remaining work, and commit/PR state.
- Prefer `context: "fork"` for implementation that needs inherited decisions. If the parent session is not persisted, use `context: "fresh"` explicitly.
- Use `acceptance: { level: "checked", ... }` for ordinary writers. Use `level: "verified"` only with a non-empty `acceptance.verify` command list that the runtime can execute itself.

**Read-only children:**
- Prefer `context: "fresh"` for adversarial reviewers inspecting the repository and diff.
- For reviewer/read-only calls, state `do not edit` in the task and omit explicit `acceptance`; allow Pi to infer lightweight read-only attestation.
- Optional hard count caps are allowed only for explicitly read-only, tightly bounded scouts, reviewers, or validators. Keep task scope narrow and size any cap from observed usage rather than an arbitrary low default.

**Large work:**
- Split large implementation into serial milestones. For each milestone: one writer, validation contract, fresh-context review/validation, one fix pass when needed, and parent acceptance before the next milestone.
- Keep task-specific acceptance and any read-only budgets visible in the per-run invocation. Do not add a global `turnBudget` for mixed-role workflows.
</pi-subagents>
