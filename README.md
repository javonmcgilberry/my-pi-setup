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

## Managed settings

Pi's live `~/.pi/agent/settings.json` remains the source of truth for ordinary
preferences changed through `/settings`. Setup reapplies only the manifest's
managed keys:

- `httpIdleTimeoutMs`
- `transport`
- `retry`
- `packages`
- `subagents`
- `vstack`

The portable defaults select SSE, disable provider-level retries, and keep
agent-level retry enabled. Secrets remain in Pi's local auth files or
environment variables and are never copied into this repository.

## Packages and shared skills

`settings.json` installs personal functionality through private Git Pi packages:

```text
git:git@github.com:javonmcgilberry/javon-pi-extensions.git
git:git@github.com:javonmcgilberry/webflow-designer-agent-browser.git
```

The Webflow skill is linked once into `~/.agents/skills`. Setup prefers the
development checkout at `~/Developer/webflow-designer-agent-browser`; otherwise
it links the checkout managed by Pi after package installation. This keeps one
Agent Skills copy visible to Pi and other compatible harnesses.

## Safety and recovery

- `setup.sh --dry-run` previews configuration changes.
- `scripts/drift.sh` is read-only.
- Replaced managed files are backed up under `~/.pi/agent/backups/`.
- `scripts/restore.sh <backup-directory>` restores a selected backup.
- Auth, sessions, caches, browser profiles, cookies, package clones, and runtime
  databases are excluded from the managed inventory.

When Pi is active, test setup changes only with isolated `PI_AGENT_DIR`,
`PI_CODING_AGENT_DIR`, and `AGENTS_SKILLS_DIR` values.
