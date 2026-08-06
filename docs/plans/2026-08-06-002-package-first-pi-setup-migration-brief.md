# Package-first Pi setup migration brief

## Approval

**Approved 2026-08-06**

## Outcome

`my-pi-setup` becomes an installable but explicitly personal Pi package. Pi
owns loading and installing the package's active extensions and all third-party
Pi packages. A smaller bootstrap owns only global settings and instructions,
package-specific configuration files that Pi packages cannot place, private
external links, and the single cross-harness skill link.

The live setup is reproducible from exact package pins without treating this
repository as the workspace for Pi core or Prewalk development. The all-in-one
`./sync` command is removed; source control, package upgrades, validation,
bootstrap application, and drift inspection are separate explicit operations.

## Current behavior

- `settings.json` lists the Pi packages loaded globally, but many npm and Git
  sources are not pinned directly in that file.
- `package.json` and `package-lock.json` mirror many live Pi packages even
  though Pi installs settings packages in its own managed npm and Git trees.
- `config/manifest.json`, `setup.sh`, and `scripts/drift.sh` copy or link active
  extensions and configuration into `~/.pi/agent`.
- Prewalk is pinned as the `prewalk` submodule, linked into
  `~/.pi/agent/packages/prewalk`, and loaded from `./packages/prewalk`.
- `./sync` pulls, optionally upgrades dependencies, stages every change,
  validates, commits, pushes, applies the setup, and checks drift.
- `README.md` tells the user to start Pi from this checkout for daily work,
  which makes repository ownership unclear when a task actually changes
  `~/Developer/pi` or Prewalk.
- The working tree already contains unrelated in-progress changes. This
  migration must not reset, stage, commit, or silently absorb them.
- Research supporting this direction is recorded in
  `docs/research/2026-08-06-pi-setup-sharing-patterns.md`.

## Decisions

1. **Package-first boundary — user confirmed.** `my-pi-setup` is primarily a Pi
   package. A thin bootstrap remains only for global files and links that Pi
   packages cannot manage.
2. **Retire `./sync` — user confirmed.** Git pull, staging, commit, push,
   tagging, upgrades, validation, bootstrap application, and drift inspection
   remain separate operations. No replacement command may combine source
   control and live deployment.
3. **Keep a reduced safety layer — user confirmed.** The bootstrap retains a
   declarative inventory, path-boundary checks, timestamped backups, restore,
   and read-only drift detection, but only for bootstrap-owned files.
4. **Pin live dependencies in `settings.json` — user confirmed.** Every npm
   source uses an exact version and every Git source uses a commit or release
   tag. The repository lockfile governs only this package's own development or
   runtime dependencies.
5. **Install Prewalk as a pinned Git package — user confirmed.** The submodule
   and generated live link are removed. `settings.local.json` may replace the
   pinned source with a local development checkout.
6. **Public but personal contract — user confirmed.** Other users may inspect,
   fork, or install the package, but the repository does not promise general
   compatibility or support for arbitrary machines.
7. **Repository-scoped Pi sessions — inferred from the reported problem and
   research.** Start Pi in the repository being changed. This repository is
   used for setup/package work, `~/Developer/pi` for Pi core, and the Prewalk
   checkout for Prewalk development.
8. **One shared Webflow skill installation — inferred from existing ownership
   rules.** The Webflow skill remains linked only under `~/.agents/skills` and
   is excluded from the Pi package manifest to prevent duplicate discovery.
9. **No live application during implementation — inferred from active-session
   safety rules.** Verification targets temporary `PI_AGENT_DIR` and
   `AGENTS_SKILLS_DIR` directories. Applying to `~/.pi/agent` is a later,
   explicit user operation after all Pi sessions close.
10. **No publication in this migration — inferred from the package/tag cycle.**
    The implementation may prepare package metadata and documented commands,
    but Git commits, pushes, tags, and live installation remain explicit work
    after review.
11. **Fold the existing context-budget extension into the personal package —
    implementation adaptation.** Clean baseline `93f110f` added
    `packages/context-budget` as a separate linked local package after this
    brief was drafted. Package-first ownership means shipping that existing
    extension from the personal package instead of preserving another bootstrap
    link.

## Scope

### In scope

- `package.json` and `package-lock.json` package metadata and dependency roles
- Exact package sources in `settings.json`
- Local source substitution in `settings.local.example.json` and
  `scripts/render-settings.mjs`
- Removal of `.gitmodules` and the `prewalk` gitlink
- Reduced ownership in `config/manifest.json`
- Bootstrap, restore, drift, inventory, and checks under `setup.sh` and
  `scripts/`
- Removal of `sync`
- CI validation in `.github/workflows/check.yml`
- Setup ownership and operating instructions in `README.md` and `AGENTS.md`
- Focused tests in `scripts/manifest.test.mjs` and existing extension test files

### Out of scope

- Changes to Pi core, Pi Lens, Prewalk source, or third-party packages
- Applying changes to the live `~/.pi/agent` while Pi sessions are active
- Publishing a Git tag or npm package
- Committing or pushing the migration
- General support guarantees for other users or machines
- Removing secret, session, cache, analytics, browser, or runtime exclusions
- Weakening tests, fixtures, or safety checks to make verification pass

## Acceptance criteria

1. `package.json` declares `my-pi-setup` as a discoverable Pi package with an
   explicit active-extension allowlist and excludes disabled extensions and the
   cross-harness Webflow skill.
2. `npm pack --dry-run` contains only intended package resources and no runtime,
   credential, browser-profile, session, cache, or unrelated machine files.
3. Every npm and Git source in `settings.json` is exactly pinned, and a focused
   check fails on any new floating source.
4. The root lockfile and README no longer claim to determine Pi-managed package
   installations.
5. Prewalk's current remote and commit are preserved as one exact Git package
   source before the submodule and generated link are removed.
6. `git submodule status` and `git ls-files --stage prewalk` no longer report a
   tracked Prewalk submodule.
7. The reduced manifest manages only global settings/instructions/config,
   private external links, the shared Webflow link, and retired migration
   targets. It does not copy or link active package extensions.
8. Existing target-boundary, symlink refusal, backup, restore, and drift tests
   continue to pass.
9. A temporary bootstrap run is idempotent, and its drift check prints
   `No managed file drift detected.`
10. The first migration of old extension and Prewalk links moves them into a
    timestamped backup instead of deleting or overwriting them.
11. `sync` is deleted, no documentation refers to it, and no remaining script
    stages, commits, pushes, pulls, tags, or upgrades dependencies.
12. README and AGENTS instructions tell users to start Pi in the repository
    being changed and accurately describe the package-first boundary.
13. `./scripts/check.sh`, `npm pack --dry-run`, and `git diff --check` pass.
14. An independent code review finds no unresolved package duplication,
    unpinned source, unsafe path handling, stale submodule reference, or public
    support overstatement.
15. Unrelated pre-existing working-tree changes remain untouched and unstaged.

## Implementation units

### U1. Define the Pi package

- Add package metadata, the `pi-package` keyword, and an explicit
  `pi.extensions` allowlist to `package.json`.
- Include `extensions/herdr-agent-state.ts`,
  `extensions/pretty-footer.ts`, `packages/context-budget`,
  `extensions/session-spend-dashboard`, and `extensions/warp-session-title.ts`.
- Exclude `disabled-extensions/clear-status.ts` and
  `skills/webflow-designer-agent-browser`.
- Remove third-party Pi packages that are present only as a live dependency
  mirror; retain dependencies needed by this package's source and tests.
- Regenerate `package-lock.json` with
  `npm install --package-lock-only --ignore-scripts`.
- Verify with manifest assertions and `npm pack --dry-run`.

### U2. Make settings pins authoritative

- Pin each npm package source to an exact version and each Git package source to
  an exact commit or tag in `settings.json`.
- Add a pin audit to `scripts/manifest.test.mjs` or a focused helper invoked by
  `scripts/check.sh`.
- Preserve the existing `packageReplacements` contract for pinned packages and
  document the Prewalk development substitution in
  `settings.local.example.json`. The owner bootstrap adds this repository's
  local package source directly and exactly once; public users install its
  pinned Git source instead.
- Remove README claims that the root lockfile controls Pi-managed packages.

### U3. Move Prewalk to Pi-managed Git installation

- Record `git -C prewalk remote get-url origin` and the exact commit from
  `git submodule status -- prewalk` before changing repository structure.
- Replace `./packages/prewalk` with that pinned Git source in `settings.json`.
- Remove `.gitmodules` and the `prewalk` gitlink.
- Remove submodule initialization/status logic from `.github/workflows/check.yml`,
  `scripts/check.sh`, setup documentation, and ownership rules.
- Declare the old live `packages/prewalk` path retired so bootstrap backs it up.

### U4. Reduce bootstrap and manifest ownership

- Remove active extension links, `package.json`, `package-lock.json`, and the
  disabled extension from live copied/linked inventory.
- Keep rendered global settings, global AGENTS, package configuration files,
  `REALTIME-SYSTEM-PROMPT.md`, private external links, the shared Webflow skill,
  and retired migration targets.
- Preserve `normalizeManifest`, `entriesFor`, `assert_safe_target_parent`,
  backup loops, `restore_pi`, `restore_shared`, and drift semantics while
  deleting categories or branches that no longer have a valid owner.
- Add regression tests for the reduced inventory, duplicate targets, path
  traversal, symlink boundaries, retirement backups, idempotence, and drift.

### U5. Separate publication from deployment

- Delete `sync`.
- Delete `scripts/update-git-pins.mjs` if no explicit tested caller remains;
  otherwise keep it only as a narrowly documented pin-inspection/update helper.
- Remove sync and automatic upgrade references from `README.md`, `AGENTS.md`,
  `scripts/check.sh`, and CI.
- Keep `scripts/check.sh`, `setup.sh`, `scripts/drift.sh`, and
  `scripts/restore.sh` as separate commands with no Git mutation.

### U6. Correct workflow and support documentation

- Rewrite install and daily-workflow sections in `README.md` around owner
  bootstrap, public Git-package installation, exact pins, local overrides, and
  repository-scoped Pi sessions.
- Update `AGENTS.md` ownership and validation rules to match the new commands
  and remove the universal-start and sync publication rules.
- State that the package is public and installable but personal and unsupported
  for general compatibility.
- Run Humanizer and Chill passes while preserving exact paths, commands, and
  safety requirements.

### U7. Verify and independently review

- Run focused script tests throughout implementation.
- Run a dry-run and two real bootstrap passes against one temporary target.
- Confirm temporary drift is clean and old paths are backed up on migration.
- Run `./scripts/check.sh`, `npm pack --dry-run`, and `git diff --check`.
- Run independent code review and fix findings without modifying verification
  assets merely to obtain a pass.

## Execution

- [x] U1. Defined the Pi package and verified its 22-file packed resource boundary.
- [x] U2. Pinned live package sources in settings and added the pin audit.
- [x] U3. Replaced the Prewalk submodule/link with an exact Git package source.
- [x] U4. Reduced bootstrap ownership while preserving and testing backup, restore, drift, and symlink safety.
- [x] U5. Deleted `sync` and separated Git, upgrades, validation, and application.
- [x] U6. Updated operating and public-support documentation and completed the required writing passes.
- [x] U7. Passed full temporary-install verification and independent standards/spec reviews.

## Verification

During implementation, run focused checks after each unit. Final verification:

```sh
node --check scripts/render-settings.mjs
node scripts/manifest.mjs validate
node --test scripts/manifest.test.mjs
npm install --package-lock-only --ignore-scripts
npm pack --dry-run
./setup.sh --dry-run

tmp="$(mktemp -d)"
PI_AGENT_DIR="$tmp/agent" AGENTS_SKILLS_DIR="$tmp/shared-skills" ./setup.sh
PI_AGENT_DIR="$tmp/agent" AGENTS_SKILLS_DIR="$tmp/shared-skills" ./setup.sh
PI_AGENT_DIR="$tmp/agent" AGENTS_SKILLS_DIR="$tmp/shared-skills" ./scripts/drift.sh

./scripts/check.sh
git diff --check
git status --short
```

Required outcomes:

- The second bootstrap is idempotent.
- Drift prints `No managed file drift detected.`
- The package tarball contains only intended resources.
- No command writes to the live agent directory.
- No unrelated working-tree change is staged, reset, or rewritten.
- All focused and full checks pass without weakened tests or fixtures.

## Risks and mitigations

- **Self-package duplication:** Test owner local-package rendering separately
  from public Git installation and assert only one package identity is loaded.
- **Pinned self-reference:** Do not require a not-yet-created tag during local
  tests. Publication and tagging are outside this implementation.
- **Prewalk pin loss:** Record and test the exact remote and commit before
  removing the submodule.
- **Duplicate Webflow skill discovery:** Exclude it from `pi.skills`; keep only
  the shared link.
- **Old live links:** Retire through the backup path, never direct deletion.
- **Unsafe target traversal:** Keep the existing root, ancestor-symlink, and
  relative-path checks covered by tests.
- **Misleading lockfile determinism:** Test settings pins directly and document
  the root lockfile's narrower role.
- **Dirty worktree scope collision:** Do not execute or commit until unrelated
  changes are separately resolved or the user explicitly chooses isolation.
- **Active Pi sessions:** Verify only in temporary directories; defer live
  bootstrap until every session is closed.

## Open blockers

None. Publishing a Git tag and applying the live setup remain explicit work
outside this implementation.
