# Javon's Pi Configuration

This private repository contains only portable Pi configuration and the small
bootstrap needed to apply it safely. Product code and product test suites live
in their own repositories.

## Repository split

| Repository | Responsibility |
| --- | --- |
| [`my-pi-setup`](https://github.com/javonmcgilberry/my-pi-setup) | Portable settings, config files, shared-skill links, bootstrap, drift, and restore |
| [`javon-pi-extensions`](https://github.com/javonmcgilberry/javon-pi-extensions) | Personal Pi extensions, context budget, footer, dashboard, and their tests |
| [`webflow-designer-agent-browser`](https://github.com/javonmcgilberry/webflow-designer-agent-browser) | Webflow browser skill, policy extensions, fixtures, benchmarks, and its 247-test suite |
| [`pi-prewalk`](https://github.com/javonmcgilberry/pi-prewalk) | Prewalk package and development source |

The two new package repositories are private. The Webflow repository can be
transferred to an organization later; while it remains personal and private,
organization owners and base permissions cannot grant access to it.

## Install

```sh
git clone git@github.com:javonmcgilberry/my-pi-setup.git ~/Developer/my-pi-setup
cd ~/Developer/my-pi-setup
./scripts/pi-update-all
```

GitHub SSH access is required because the package repositories are private.
The updater refuses to run while Pi is open.

## Routine update

Close every Pi session, then run:

```sh
pi-update-all
```

The command requires a clean configuration checkout. It fast-forwards the
checkout, applies settings, runs Pi's native `pi update --all`, reapplies links
provided by installed packages, and verifies drift. It does not run product
tests and does not create commits.

To change configuration, edit this repository and land the change separately:

```sh
./scripts/land.sh --message "describe the configuration change" --push
```

The normal configuration check is small. `./scripts/check.sh --full` adds the
isolated setup matrix when bootstrap behavior itself changes.

## Live settings and install defaults

Pi reads `~/.pi/agent/settings.json`, and that live file is authoritative for
user preferences. Setup reads it before rendering and preserves every existing
top-level setting except `packages`. The package list remains managed because
setup uses it as the install inventory and swaps package locators for canonical
local checkouts when they exist.

The tracked `settings.json` is a clean-install starting point. Its transport,
retry, subagent, model, theme, and other values fill a new settings file, but a
later setup run does not restore those values over live choices made through
`/settings`. In a trusted project, `<project>/.pi/settings.json` is merged over
the global file, so project settings still take precedence for that project.

The clean-install subagent defaults use Luna with role-specific thinking:
scouts use low, researchers and delegates use medium, workers and reviewers
use high, and the oracle uses max. Once installed, these are normal live
preferences and setup leaves them alone.

Secrets remain in Pi's local auth files or environment variables and are never
copied into this repository.

The installed `AGENTS.md` also sets the operating policy for delegated work.
Ordinary runs use Pi's 30-minute timeout unless a measured task needs an
explicit limit. Tightly scoped read-only reviews use a soft tool limit and the
string wildcard `block: "*"` so the child must stop inspecting and return a
verdict. Broad research is split into checkpointed milestones, read-only
reviews omit acceptance contracts, and report writers receive one output path.

## Packages and shared skills

Tracked settings keep private Git package sources so a clean machine can install
the personal repositories:

```text
git:git@github.com:javonmcgilberry/javon-pi-extensions.git
git:git@github.com:javonmcgilberry/webflow-designer-agent-browser.git
```

On this machine, setup prefers the Git working trees at
`~/Developer/javon-pi-extensions` and
`~/Developer/webflow-designer-agent-browser`. Pi reads those directories
directly when a session starts, so local code does not need to be pushed before
Pi can use it. If either checkout is missing, setup keeps that repository's
private Git source and `pi update` refreshes Pi's managed clone.

The Webflow skill is linked once into `~/.agents/skills` using the same local
checkout first and managed-clone fallback. This keeps one Agent Skills copy
visible to Pi and other compatible harnesses.

## Safety and recovery

- `setup.sh --dry-run` previews configuration changes.
- `scripts/drift.sh` is read-only.
- Replaced managed files are backed up under `~/.pi/agent/backups/`.
- `scripts/restore.sh <backup-directory>` restores a selected backup.
- Auth, sessions, caches, browser profiles, cookies, package clones, and runtime
  databases are excluded from the managed inventory.

When Pi is active, test setup changes only with isolated `PI_AGENT_DIR`,
`PI_CODING_AGENT_DIR`, and `AGENTS_SKILLS_DIR` values.
