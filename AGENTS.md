# Repository contract

This repository is the source of truth for Javon's Pi setup. Work from the
repository that owns each change; `~/.pi/agent` contains installed output.

## Ownership and architecture

- Edit tracked configuration, package metadata, scripts, skills, and linked
  extensions here. Local extensions live in `extensions/`, the context-budget
  package lives in `packages/context-budget/`, tracked defaults and package
  locators live in `settings.json`, and package metadata lives in
  `package.json`. Routine npm and Git packages float so Pi's native
  `pi update --extensions` command can update them. Packages with an explicit
  publication boundary are declared in `config/manifest.json`; Prewalk is the
  only current exact source.
- Treat `config/manifest.json` as the authoritative managed-install inventory.
  Update it before changing setup, drift, validation, retirement, or restore
  behavior.
- Treat root `PRODUCT.md` as shared product authority for tracked skills,
  extensions, terminal/TUI behavior, and localhost interfaces.
- Make Pi core changes in `~/Developer/pi`, rather than the globally installed
  package. Keep Pi-managed checkouts under `~/.pi/agent/npm/node_modules` and
  `~/.pi/agent/git` read-only.
- Use the unmodified upstream `npm:pi-subagents` package. Keep the retired
  custom fork and its Prewalk execution-profile policy retired.
- Put machine-only overrides in ignored `settings.local.json`. Keep credentials,
  browser profiles, cookies, and runtime data outside tracked files.
- An explicit `packageReplacements` entry in `settings.local.json` always wins
  over its tracked remote locator. Do not infer replacements from checkout
  names or nearby directories; stale and retired clones must not load silently.

This repository is an installable personal Pi package. Its bootstrap renders
global settings plus the few files and shared links that Pi packages cannot
place.

### Prewalk source boundary

- Edit Prewalk in its owning checkout. During local development, use the
  ignored `settings.local.json` replacement; its unpinned package locator stays
  valid when the tracked SHA changes. For source-only changes, restart Pi and
  leave the tracked SHA unchanged.
- Without that replacement, clean installs use the exact remotely fetchable
  `git:github.com/javonmcgilberry/pi-prewalk@...` pin in `settings.json`; Pi
  owns the generated checkout under `~/.pi/agent/git`.
- To publish a new default remote version, pull or test the owning checkout,
  push its commit first, then update the tracked SHA here. `scripts/check.sh`
  verifies that each exact Git pin is remotely fetchable.

### Shared Webflow skill

Use `~/.agents/skills` as the sole discovery link for
`skills/webflow-designer-agent-browser`, where Pi and other compatible
harnesses can find it. A second link under `~/.pi/agent/skills` causes a
skill-name collision. Keep its browser profile and runtime state as private
machine data under `~/.config`.

### Skill design

When creating or revising a Pi skill, keep the skill surface small and
inspectable. Put deterministic, repeatable behavior behind narrow executable
commands; use `SKILL.md` for the judgment and context the model actually needs.
Expose lifecycle state and idempotent operations where practical instead of
depending on repeated prompt instructions.

## Standard change workflow

### Proportional execution and time discipline

- Use the smallest workflow that can safely satisfy the request. Routine pin,
  package, and configuration updates are not large-work projects.
- For a straightforward update, confirm only the requested versions and any
  stated runtime floor, make the edits, then run each repository-required
  validation once. Batch final wording edits before validation so successful
  full checks are not repeated.
- Do not launch subagents or reviewer passes, perform broad package-source
  research, add security audits, or build multiple smoke-test matrices for
  routine maintenance unless the user explicitly requests that depth or a
  concrete validation failure makes it necessary. Escalate one step at a time
  from the actual failure.
- If routine maintenance is likely to exceed ten minutes, needs more than one
  retry, or starts expanding beyond the requested scope, stop and ask before
  continuing. Report a live-application or restart boundary promptly instead
  of turning it into a side investigation.

1. Start in `~/Developer/my-pi-setup`, run `git status --short --branch`, and
   preserve existing work. Run Pi from the repository being changed.
2. Create a branch or worktree only when the user asks for a PR or isolation.
   Remove merged temporary branches and worktrees when the work is complete.
3. Use `pi update --extensions` for routine package updates. Add or move an
   exact package source only when the user wants a reviewed publication
   boundary, then review that change like code.
4. When installed components, configuration, commands, ownership, live paths,
   user-visible behavior, safety rules, or data handling change, update root
   `README.md` in the same change. Check the wording against this repository or
   the owning package's source, then run the Humanizer pass followed by the
   Chill pass. Preserve exact paths, settings, commands, safety rules, and
   uncertainty through both passes.
5. Commit through `./scripts/land.sh --message <text>`, the single supported
   commit path. It runs `check.sh` before staging anything, so the secret scan,
   forbidden-path scan, and manifest inventory check cannot be skipped. Use
   `--path` to scope a commit, `--push` to publish, and `--full` for the
   complete suite. Do not hand-roll `git add`/`git commit` here; a clean tree
   makes the script a no-op, so it is always safe to call.
6. Keep dependency upgrades, validation, and live application as separate
   operations. `setup.sh` is configuration-only; pulling, tagging, and
   dependency upgrades happen separately from landing a commit.
7. Before completion, run `./scripts/check.sh` and use the read-only
   `./scripts/drift.sh` for comparison with the live setup. After setup or
   package changes, also run `npm pack --dry-run`.

Code-only changes generally need a Pi restart. Rendered settings, copied
configuration, and bootstrap-inventory changes require `setup.sh`.

### Isolated validation and live application

- While any Pi session is active, reserve one temporary directory for
  `PI_AGENT_DIR`, `AGENTS_SKILLS_DIR`, and `PI_CODING_AGENT_DIR`. Run
  `./setup.sh` and `./scripts/drift.sh` there, and start the test Pi process with
  those same variables. Use the live defaults only after every Pi session has
  closed.
- To apply live changes, close every Pi session, then run
  `env -u PI_AGENT_DIR -u AGENTS_SKILLS_DIR -u PI_CODING_AGENT_DIR ./setup.sh`,
  run `./scripts/drift.sh`, run `pi update --extensions`, and restart Pi.
- Apply changed live configuration exclusively with `setup.sh`; `/reload` does
  not cross that boundary. There is no in-session or detached setup helper.
- After package locators change, apply `setup.sh` before running
  `pi update --extensions`. Routine updates need only the native Pi command and
  a restart.

## Related-session coordination

Use `/skill:pi-intercom` to coordinate with other local Pi sessions working in
the same codebase, a reference codebase, or a related repository when
coordination is useful. Work independently for unrelated codebases, trivial
questions, and tasks you can complete safely without coordination. Prefer
`send` for notifications; use `ask` only when progress is blocked on a response.

## Large-context routing

Route large reads, logs, research, and web payloads through top-level `ctx_*`
tools. Reserve Code Mode `exec_command` for small bounded shell output and
mutations. Return only the answer needed; keep full `FILE_CONTENT` payloads out
of model output.

## Worktree dependencies

Git worktrees do not automatically share installed dependencies. Before
installing again, point a worktree at the main checkout's dependencies:

```sh
MAIN_CHECKOUT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
ln -s "$MAIN_CHECKOUT/node_modules" node_modules  # when node_modules is missing
export NODE_PATH="$MAIN_CHECKOUT/node_modules"
export PATH="$MAIN_CHECKOUT/node_modules/.bin:$PATH"
```

The `node_modules` symlink is required for scripts that invoke
`./node_modules/.bin/*`; `NODE_PATH` alone is insufficient. Use the worktree's
own dependencies when its dependency manifest or lockfile differs, unless the
main checkout already has the matching dependency graph installed.

## Pi subagents

Use Pi subagents with mutation-safe orchestration.

### Mutation-capable children

- Leave `turnBudget` and `toolBudget` unset for implementation workers, fix
  workers, edit-authorized reviewers, and every other child that may mutate
  files. Assistant-turn and tool-call caps are not delivery-safety boundaries.
- Assign one narrow, serial milestone to exactly one writer in a cwd or
  worktree. Keep concurrent writers out of the same worktree.
- Give elapsed `timeoutMs` or `maxRuntimeMs` enough margin. A timeout is not a
  mutation-safe boundary. For a checkpoint, request it before the deadline and
  have the child emit it after the current tool returns, including changed
  files, build/test state, remaining work, and commit/PR state.
- Prefer `context: "fork"` when implementation needs inherited decisions. Use
  `context: "fresh"` explicitly when the parent session is not persisted.
- Use `acceptance: { level: "checked", ... }` for ordinary writers. Use
  `level: "verified"` only with a non-empty `acceptance.verify` command list
  that the runtime can execute itself.

### Read-only children

- Prefer `context: "fresh"` for adversarial reviewers inspecting the repository
  and diff.
- State `do not edit` in reviewer and read-only tasks, and omit explicit
  `acceptance` so Pi can infer lightweight read-only attestation.
- Apply hard count caps only to explicitly read-only, tightly bounded scouts,
  reviewers, or validators. Keep the task narrow and size caps from observed
  usage rather than an arbitrary low default.

### Large work

- Split large implementation into serial milestones. For each milestone, use
  the mutation-capable writer rules above, a validation contract,
  fresh-context review or validation, one fix pass when needed, and parent
  acceptance before the next milestone.
- Keep task-specific acceptance and read-only budgets visible in each run.
  Leave global `turnBudget` unset for mixed-role workflows.
