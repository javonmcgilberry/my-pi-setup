<my-pi-setup-workflow>
This repository is the source of truth for Javon's Pi setup. Future agents must
work here instead of treating `~/.pi/agent` as editable source.

**Ownership:**
- Edit tracked configuration, package metadata, scripts, skills, and linked extensions in this repository.
- Treat root `PRODUCT.md` as shared product authority for tracked skills, extensions, terminal/TUI behavior, and localhost interfaces.
- Edit Pi core in `~/Developer/pi`, not in the globally installed package.
- Edit Prewalk in its owning checkout. Normal installs use the exact Git commit in `settings.json`; use `settings.local.json` to replace it with a local checkout during development.
- Use the unmodified upstream `npm:pi-subagents` package. Do not restore the retired custom fork or its Prewalk execution-profile policy.
- Never edit Pi-managed code under `~/.pi/agent/npm/node_modules` or `~/.pi/agent/git`.
- Put machine-only overrides in ignored `settings.local.json`; never commit credentials, browser profiles, cookies, or runtime data.
- Treat `config/manifest.json` as the authoritative managed install inventory. Update it before changing setup, drift, validation, retirement, or restore behavior.

**Change workflow:**
1. Start Pi in the repository being changed and inspect its `git status` before editing. Use this repository only for setup/package work, `~/Developer/pi` for Pi core, and each package's own checkout for package work.
2. Make setup changes here. Make Pi core, Prewalk, and package-specific changes in their owning checkouts.
3. When a change affects installed components, configuration, commands,
   ownership, paths used by the live setup, user-visible behavior, or data
   handling, update the root `README.md` in the same change. Check the wording
   against evidence in this repository or in the package's own source. Run the
   Humanizer pass, then the Chill pass. Both must preserve exact paths,
   settings, commands, safety rules, and uncertainty.
4. Run `./scripts/check.sh`. Use `./scripts/drift.sh` for a read-only comparison with the live setup.
5. Do not create a branch or worktree unless the user asks for a PR or isolation. Remove merged temporary branches/worktrees when that work is complete.
6. Keep source control, dependency upgrades, validation, and live application separate. `setup.sh` must never stage, commit, pull, push, tag, or upgrade dependencies.
7. Update exact npm and Git pins only when the user explicitly asks for upgrades, then review those changes like code.
8. When Pi sessions are active, validate with both `PI_AGENT_DIR` and `AGENTS_SKILLS_DIR` inside one temporary directory. Apply the live setup later with `./setup.sh`, after every Pi session is closed, then run `./scripts/drift.sh`.

**Current architecture:** This repository is an installable personal Pi package.
The bootstrap renders global settings and the few files or shared links that Pi
packages cannot place. Prewalk is installed from the exact Git commit in
`settings.json`; pi-subagents uses the exact upstream npm release named there.

The tracked, cross-harness Webflow Designer skill is linked from
`skills/webflow-designer-agent-browser` into `~/.agents/skills`, where Pi and
other compatible harnesses can discover the same installation. Do not also
link it under `~/.pi/agent/skills`; duplicate discovery causes a skill-name
collision. Its browser profile and runtime state remain private machine data
under `~/.config` and are never tracked.
</my-pi-setup-workflow>

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
