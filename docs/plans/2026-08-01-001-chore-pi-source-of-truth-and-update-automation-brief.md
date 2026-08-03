# Pi source-of-truth and update automation brief

## Outcome

The Pi setup has one clear ownership rule: portable configuration and small
owned extensions live in `my-pi-setup`; machine-only overrides stay in an
ignored local file; owned packages live under `~/webdev`; and
`~/.pi/agent` contains generated configuration, runtime data, disposable
package installs, and links back to owned source.

The Pi fork remains safely backed up without a risky migration of old feature
branches. GitHub runs a small setup check and opens one grouped monthly npm
update pull request. It does not auto-merge changes or rewrite the fork.

After the setup work is stable, `pi-prewalk` gets a full documentation pass so
its GitHub page matches the code people can actually install and run.

## Current behavior

- `javonmcgilberry/pi` `main` and `earendil-works/pi` `main` both point to
  `71efc6f0c1909874ec8c944637a9ae7fc0e2d508`. The fork is already current.
- The live `pi` command is the globally installed Pi 0.83.0 at
  `/Users/javonmcgilberry/.nvm/versions/node/v22.23.1/bin/pi`. It does not run
  the local Pi fork.
- `feat/session-only-model-selection` has three local commits, is not pushed,
  and is 335 upstream commits behind current `origin/main`.
- `fix/auto-compaction-mid-turn` has two commits, is pushed to the fork, and is
  also 335 upstream commits behind.
- The Pi checkout has one unrelated `.gitignore` edit for `.cache_ggshield`.
- `my-pi-setup` copies global settings and small extensions into
  `~/.pi/agent`, while Prewalk and Warp use links. Direct edits to the live
  copies have caused the tracked and installed configurations to drift.
- The live settings point directly to
  `/Users/javonmcgilberry/webdev/pi-subagents`, load Context Mode from
  `git:github.com/javonmcgilberry/context-mode`, and load Prewalk through
  `./packages/prewalk`.
- The Prewalk link correctly targets `/Users/javonmcgilberry/webdev/pi/prewalk`.
- The Warp extension link correctly targets the Warp checkout, but that checkout
  still lives under `~/.pi/agent/warp-pi-gateway` instead of `~/webdev`.
- The tracked and live setup currently differ in `settings.json`, `mcp.json`,
  `pi-codex-conversion.json`, and `prewalk.json`. The live MCP file adds the
  read-only Buildkite endpoint. No credential is present in that difference.
- The private `javonmcgilberry/warp-pi-gateway` repository now exists. Its
  checkout has four active modified files that must be preserved.

## Decisions

1. `my-pi-setup` owns portable global configuration. Files under
   `~/.pi/agent` are installed output or runtime state, not editable source.
2. An ignored local override file owns absolute paths, temporary development
   sources, and machine-only preferences. The installer merges it with tracked
   defaults before writing the live configuration.
3. Owned code lives under `~/webdev`. Locally developed packages and small
   owned extensions are linked into `~/.pi/agent` rather than copied.
4. Pi-managed Git clones under `~/.pi/agent/git` and npm packages under
   `~/.pi/agent/npm/node_modules` are disposable installs and must never be
   edited directly.
5. The globally installed stock Pi remains the normal runtime. The Pi fork is a
   development and upstream-contribution checkout, not the source of the live
   binary.
6. Fork syncing stays manual with
   `gh repo sync javonmcgilberry/pi -b main`. There is no scheduled fork-sync
   workflow.
7. GitHub automation is limited to CI for `scripts/check.sh` and one grouped
   monthly npm dependency pull request. Nothing auto-merges, publishes, or
   deploys.
8. The old Pi feature branches are backed up and left alone. They are not
   rebased during setup cleanup.
9. `.cache_ggshield` belongs in the user's global Git ignore, not Pi's tracked
   `.gitignore`.
10. Warp remains private. After its checkout moves, it receives a focused secret
    and portability review before any further publication decision.
11. Prewalk documentation is updated last, after the installed paths and
    integration rules are settled. The final writing must be plain, direct, and
    free of stale promises or internal planning language.
12. Approved repository changes are committed and pushed serially after their
    focused checks pass. No pull request, merge, release, or public visibility
    change is part of this work.
13. `settings.local.json` has two explicit sections: `settings` deep-merges
    object values and replaces arrays, while `packageReplacements` swaps one
    tracked package source for one local checkout without duplicating the whole
    package list.

## Scope

### In scope

- `/Users/javonmcgilberry/webdev/pi`
- `/Users/javonmcgilberry/webdev/pi/upstream/pi`
- `/Users/javonmcgilberry/.pi/agent/warp-pi-gateway`, moved to
  `/Users/javonmcgilberry/webdev/warp-pi-gateway`
- Installed links and generated config under `/Users/javonmcgilberry/.pi/agent`
- `javonmcgilberry/my-pi-setup` GitHub Actions and Dependabot configuration
- A read-only secret and portability review of `warp-pi-gateway`, followed by
  narrowly justified fixes
- User-facing documentation in
  `/Users/javonmcgilberry/webdev/pi/prewalk`, followed by a direct update to
  `https://github.com/javonmcgilberry/pi-prewalk`

### Out of scope

- Rebasing or redesigning either old Pi feature branch
- Installing the Pi fork as the normal Pi runtime
- Automatic merges, package publishing, deployment, or scheduled fork rewrites
- Deleting sessions, analytics, checkpoints, backups, caches, worktrees, or
  package install directories
- Editing npm packages or Pi-managed Git clones in place
- Broad dependency upgrades outside the reviewed monthly pull-request flow

## Acceptance criteria

1. Fork and upstream `main` still have zero divergence after a fresh fetch.
2. `feat/session-only-model-selection` exists on the user's fork before local
   cleanup touches its checkout.
3. The Pi checkout's tracked `.gitignore` is clean, and `.cache_ggshield` is
   ignored through the user's global Git excludes file.
4. `my-pi-setup` documents one edit location for every custom component.
5. `settings.local.json` is ignored, optional, schema-checked, and merged
   deterministically with tracked defaults. A checked-in example explains the
   format without including local paths or credentials.
6. A dry run reports the generated result and drift without writing files.
7. Herdr and pretty-footer load through links to `my-pi-setup`, not copied live
   files.
8. Prewalk continues to link to the pinned submodule checkout.
9. Warp lives at `/Users/javonmcgilberry/webdev/warp-pi-gateway`; its Git history,
   remote, ignored local files, and four active modifications survive the move.
10. The live Warp extension link targets the moved checkout.
11. Context Mode edits are made in `/Users/javonmcgilberry/webdev/context-mode`;
    pi-subagents edits are made in `/Users/javonmcgilberry/webdev/pi-subagents`;
    install clones are documented as disposable.
12. CI runs `./scripts/check.sh` on pull requests and pushes to `main`.
13. Dependabot opens grouped monthly npm updates and cannot auto-merge them.
14. The Warp review finds no tracked secrets. Its install and README paths do
    not depend on the old checkout location, and any remaining host assumptions
    are documented plainly.
15. No session, credential, analytics, backup, cache, checkpoint, worktree, or
    unrelated uncommitted code is removed.
16. Prewalk's README accurately explains its current lifecycle, supported stock
    Pi baseline, configuration, optional integrations, compaction guard,
    analytics, limitations, and verification commands.
17. Old implementation plans and research are clearly historical and are not
    presented as current setup instructions.
18. The Prewalk documentation is concise enough to understand on a first read,
    keeps required technical detail, and does not use inflated or generic AI
    writing.

## Implementation units

### U1. Back up and clean the Pi fork checkout

- Fetch `origin` and `fork`, then record zero `main` divergence.
- Push `feat/session-only-model-selection` to the user's fork without rebasing.
- Configure or reuse a global Git excludes file containing
  `.cache_ggshield`.
- Restore only the local `.gitignore` noise. Leave both feature branches and
  the auto-compaction worktree intact.

### U2. Make configuration ownership explicit

- Add an ignored `settings.local.json` contract and a safe example file.
- Add a small deterministic merge step to `setup.sh`. Nested objects merge;
  local scalar and array values replace tracked values. Reject malformed JSON.
- Promote stable, non-secret live choices into tracked files where they belong,
  including the Buildkite MCP endpoint. Keep absolute development paths and
  temporary package substitutions local.
- Make dry-run output distinguish tracked defaults, local overrides, generated
  files, and links.
- Update `scripts/check.sh` and README ownership instructions.

### U3. Link owned code and move Warp

- Replace copied Herdr and pretty-footer installs with links to their files in
  `my-pi-setup`, preserving any differing live file before replacement.
- Keep Prewalk's existing submodule link.
- Stop Pi and Warp processes only if they hold the checkout during the move.
- Check for another active Pi session using the Warp checkout and coordinate or
  wait before moving it. Never move a working directory out from under another
  writer.
- Move the Warp Git checkout to `~/webdev/warp-pi-gateway` without cloning over
  or resetting its active changes.
- Recreate the live Warp extension link through Warp's installer or an exact
  link update, then verify its resolved target.
- Do not move Context Mode or pi-subagents install clones; document the correct
  editable development checkouts instead.

### U4. Add low-noise GitHub automation

- Add a workflow that runs `./scripts/check.sh` on pull requests and pushes to
  `main`.
- Add monthly grouped npm Dependabot configuration for `my-pi-setup`.
- Do not add fork-sync, auto-merge, publish, or deploy workflows.
- After U1 through U4 pass, commit and push `my-pi-setup` `main`.

### U5. Review Warp for secrets and portability

- Check tracked history and the working tree with the available secret scanner;
  inspect `.gitignore`, `.env` handling, Docker/Compose inputs, install paths,
  and shell assumptions.
- Replace hard-coded old checkout paths and personal-only defaults when a
  portable equivalent exists.
- Document unavoidable macOS, Docker, Tailscale, Warp, and Pi requirements.
- Run Warp's focused build and tests without changing or exposing local secrets.
- Commit and push the reviewed Warp changes to its existing private `main`
  branch after verification.

### U6. Bring Prewalk's GitHub documentation up to date

- Compare the README and user-facing docs against the current extension,
  configuration schema, package metadata, commands, tests, and setup layout.
- Rewrite the README around the normal user path: what Prewalk does, how to
  install it, how a run moves from planner to executor, what gets stored, what
  optional integrations change, and what Prewalk deliberately refuses to do.
- Correct stale version, routing, compaction, analytics, smoke-test, and source
  ownership claims. Do not turn internal plans into product promises.
- Mark old plans and research as historical where their location or wording
  could confuse a reader. Do not rewrite archival evidence just for style.
- Run a final humanizer and plain-language pass without removing necessary
  technical precision.
- Run focused documentation, type, and extension checks, then commit and push
  the finished documentation to `javonmcgilberry/pi-prewalk` `main`.

## Execution

- [x] U1. Backed up `feat/session-only-model-selection` to the fork, moved
  `.cache_ggshield` into `~/.config/git/ignore`, restored Pi's `.gitignore`, and
  confirmed `fork/main...origin/main` is `0 0`.
- [x] U2. Added deterministic tracked-plus-local settings rendering, pinned the
  forked package defaults, promoted stable live MCP and extension settings,
  documented edit locations, and verified both dry-run and temporary install
  paths with `./scripts/check.sh` and a temporary `PI_AGENT_DIR` setup run.
- [x] U3. Linked Herdr and pretty-footer to `my-pi-setup`, preserved Prewalk's
  link, moved the private Warp checkout to `~/webdev/warp-pi-gateway`, and
  retargeted both its Pi extension and CLI links. The same four active Warp
  modifications and original commit remained after the move.
- [x] U4. Added push/PR setup checks and one grouped monthly npm Dependabot
  update, verified the YAML and local check, then pushed `my-pi-setup` main at
  `3a19c26` with no auto-merge, publish, deploy, or fork-sync workflow.
- [x] U5. Confirmed Git history and tracked working files contain no secrets,
  removed a personal Tailnet hostname from docs, fixed old and configurable Pi
  paths, made stop remove the credential volume, hid raw upstream errors, and
  pushed private Warp main at `8d0b8cb`. `npm run build`, all 5 tests, shell and
  Node syntax, Compose validation, and `git diff --check` passed. Ignored local
  `.env` and runtime copies still contain the credentials they are expected to
  hold and were not committed.
- [x] U6. Rewrote Prewalk's README around the install-and-run path, moved local
  analytics details into a focused guide, marked plans and research as
  historical, corrected the stale RPC fixture, and pushed `pi-prewalk` main at
  `71d01d6`. Lint, typecheck, all 300 tests, the stock Pi RPC smoke, current-doc
  link checks, `npm pack --dry-run`, and `git diff --check` passed. The Docker
  benchmark integration remained intentionally skipped.

## Verification

- `git rev-list --left-right --count fork/main...origin/main` returns `0 0` in
  the Pi checkout.
- `git branch -r --contains feat/session-only-model-selection` includes the
  user's fork branch after publication.
- `git status --short` in both Pi worktrees shows no cleanup-created changes.
- `./setup.sh --dry-run --skip-install` writes nothing and explains the merged
  result.
- A temporary `PI_AGENT_DIR` setup run creates valid JSON and links that resolve
  to the expected source files.
- `./scripts/check.sh` passes locally and in GitHub Actions.
- `readlink` confirms Prewalk, Herdr, pretty-footer, and Warp targets.
- `git -C ~/webdev/warp-pi-gateway status --short` preserves the pre-move active
  changes.
- Warp's focused build and tests pass after portability fixes.
- Prewalk `npm run typecheck`, focused extension tests, README links, documented
  commands, and `npm pack --dry-run` all pass after the documentation update.
- `git diff --check` passes in every edited repository.

## Open blockers

None. The implementation must remain serial because it moves an active checkout
and changes live links.

## Approval

Approved 2026-08-01
